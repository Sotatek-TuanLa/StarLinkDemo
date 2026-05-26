using System.Windows;

namespace StarLinkPOC.Models
{
    /// <summary>Single object detection result from YOLO inference.</summary>
    public record Detection(
        int     ClassId,
        string  Label,
        float   Confidence,
        /// <summary>Bounding box in original frame pixel coordinates.</summary>
        Rect    BoundingBox
    );
}
