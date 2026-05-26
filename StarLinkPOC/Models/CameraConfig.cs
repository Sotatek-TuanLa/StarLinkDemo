namespace StarLinkPOC.Models
{
    /// <summary>
    /// Holds all configuration needed to connect to an IP camera via RTSP.
    /// </summary>
    public class CameraConfig
    {
        /// <summary>Camera IP address or hostname (the "Camera ID").</summary>
        public string Host { get; set; } = string.Empty;

        /// <summary>RTSP login username. Defaults to "admin" for most cameras.</summary>
        public string Username { get; set; } = "admin";

        /// <summary>Camera login password.</summary>
        public string Password { get; set; } = string.Empty;

        /// <summary>RTSP port. Standard is 554.</summary>
        public int Port { get; set; } = 554;

        /// <summary>
        /// Stream path appended after the host.
        /// Common values:
        ///   Hikvision  → /Streaming/Channels/101
        ///   Dahua      → /cam/realmonitor?channel=1&subtype=0
        ///   Generic    → /stream
        /// </summary>
        public string StreamPath { get; set; } = "/Streaming/Channels/101";

        /// <summary>Builds the full RTSP URL from config components.</summary>
        public string BuildRtspUrl()
        {
            // rtsp://username:password@host:port/path
            var encodedPass = Uri.EscapeDataString(Password);
            var encodedUser = Uri.EscapeDataString(Username);
            var path = StreamPath.StartsWith('/') ? StreamPath : "/" + StreamPath;
            return $"rtsp://{encodedUser}:{encodedPass}@{Host}:{Port}{path}";
        }
    }
}
