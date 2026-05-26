import argparse
import time
import cv2
import numpy as np
import onnxruntime as ort

def parse_args():
    parser = argparse.ArgumentParser(description="YOLOv8 ONNX RTSP Live Stream Inference")
    parser.add_argument("--model", type=str, required=True, help="Path to your exported .onnx model file")
    parser.add_argument("--rtsp", type=str, required=True, help="RTSP stream URL (e.g., rtsp://admin:password@ip:554/path)")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold (default: 0.25)")
    parser.add_argument("--iou", type=float, default=0.45, help="IoU threshold for Non-Maximum Suppression (default: 0.45)")
    parser.add_argument("--gpu", action="store_true", help="Use GPU (CUDA) if available")
    return parser.parse_args()

def preprocess(frame, input_width, input_height):
    """
    Preprocess image: resize to model input dimensions, normalize to [0, 1],
    transpose dimensions to [channels, height, width] and add batch dimension [1, channels, height, width]
    """
    # Resize and maintain aspect ratio or pad
    img = cv2.resize(frame, (input_width, input_height))
    # Convert BGR to RGB
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    # Normalize to [0.0, 1.0]
    img = img.astype(np.float32) / 255.0
    # HWC to CHW
    img = img.transpose(2, 0, 1)
    # Add batch dimension
    img = np.expand_dims(img, axis=0)
    return img

def postprocess(outputs, original_w, original_h, input_w, input_h, conf_threshold, iou_threshold):
    """
    Parses the raw YOLOv8 ONNX output tensor and performs Non-Maximum Suppression.
    YOLOv8 outputs a tensor of shape [1, 4 + num_classes, 8400].
    """
    predictions = np.squeeze(outputs[0])  # Shape: [84, 8400]
    
    # Transpose to [8400, 84]
    predictions = predictions.T
    
    boxes = []
    confidences = []
    class_ids = []
    
    num_classes = predictions.shape[1] - 4
    
    for pred in predictions:
        scores = pred[4:]
        class_id = np.argmax(scores)
        confidence = scores[class_id]
        
        if confidence >= conf_threshold:
            # Box format: [center_x, center_y, width, height]
            cx, cy, w, h = pred[0:4]
            
            # Map coordinates from input_w/h back to original frame dimensions
            x_scale = original_w / input_w
            y_scale = original_h / input_h
            
            left = int((cx - w / 2) * x_scale)
            top = int((cy - h / 2) * y_scale)
            width = int(w * x_scale)
            height = int(h * y_scale)
            
            boxes.append([left, top, width, height])
            confidences.append(float(confidence))
            class_ids.append(int(class_id))
            
    # Apply Non-Maximum Suppression (NMS) to eliminate overlapping boxes
    indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_threshold, iou_threshold)
    
    final_detections = []
    if len(indices) > 0:
        # NMSBoxes returns a flat list of indices or a 2D array depending on cv2 version
        for i in indices.flatten():
            final_detections.append({
                "box": boxes[i],
                "confidence": confidences[i],
                "class_id": class_ids[i]
            })
            
    return final_detections

def main():
    args = parse_args()
    
    print(f"Loading ONNX Model: {args.model}")
    providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if args.gpu else ['CPUExecutionProvider']
    
    try:
        session = ort.InferenceSession(args.model, providers=providers)
    except Exception as e:
        print(f"Error loading ONNX Session: {e}")
        print("Falling back to CPUExecutionProvider...")
        session = ort.InferenceSession(args.model, providers=['CPUExecutionProvider'])
        
    model_inputs = session.get_inputs()
    input_shape = model_inputs[0].shape
    # YOLOv8 input is usually [1, 3, 640, 640]
    input_height, input_width = input_shape[2], input_shape[3]
    print(f"Model Input Dimensions: {input_width}x{input_height}")
    
    # Load class names if available, otherwise use index numbers
    # Standard YOLO models might include metadata. We default to generic labels.
    class_names = {}
    try:
        meta = session.get_modelmeta().custom_metadata_map
        if 'names' in meta:
            # 'names' is stored as a stringified dict: "{0: 'person', 1: 'bicycle', ...}"
            import ast
            class_names = ast.literal_eval(meta['names'])
    except Exception:
        pass

    print(f"Connecting to RTSP Stream: {args.rtsp}")
    cap = cv2.VideoCapture(args.rtsp)
    
    if not cap.isOpened():
        print("Error: Could not open RTSP video stream.")
        return
        
    cv2.namedWindow("YOLOv8 RTSP AI LiveView", cv2.WINDOW_NORMAL)
    
    print("AI LiveView Started. Press 'q' in the window to quit.")
    
    fps_start_time = time.time()
    fps_counter = 0
    fps_text = "FPS: 0"
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Stream ended or frame dropped. Reconnecting...")
            time.sleep(1)
            cap.open(args.rtsp)
            continue
            
        original_h, original_w = frame.shape[:2]
        
        # Preprocess
        input_data = preprocess(frame, input_width, input_height)
        
        # Run ONNX inference
        outputs = session.run(None, {model_inputs[0].name: input_data})
        
        # Postprocess detections (Thresholding + NMS)
        detections = postprocess(outputs, original_w, original_h, input_width, input_height, args.conf, args.iou)
        
        # Draw detections
        for det in detections:
            x, y, w, h = det["box"]
            conf = det["confidence"]
            class_id = det["class_id"]
            
            label = class_names.get(class_id, f"Class {class_id}")
            caption = f"{label} {conf:.2f}"
            
            # Color mapping based on class ID for variety
            color = (int((class_id * 50) % 255), int((class_id * 80 + 100) % 255), int((class_id * 120 + 50) % 255))
            
            # Draw box
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            
            # Draw text background
            text_size = cv2.getTextSize(caption, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
            cv2.rectangle(frame, (x, y - text_size[1] - 5), (x + text_size[0], y), color, -1)
            
            # Draw text
            cv2.putText(frame, caption, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            
        # Calculate FPS
        fps_counter += 1
        if (time.time() - fps_start_time) > 1.0:
            fps_text = f"FPS: {fps_counter}"
            fps_counter = 0
            fps_start_time = time.time()
            
        cv2.putText(frame, fps_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2, cv2.LINE_AA)
        
        # Render frame
        cv2.imshow("YOLOv8 RTSP AI LiveView", frame)
        
        # Check for quit key
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()
    print("AI LiveView Stopped.")

if __name__ == "__main__":
    main()
