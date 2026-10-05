using System.Buffers.Binary;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;

const int Width = 1088;
const int Height = 1280;
const int RawBytes = Width * Height * 10 / 8;
const int HeaderBytes = 64;
const string Url = "http://127.0.0.1:8091/";

var sshTarget = args.Length > 0 ? args[0] : "ubuntu@pi-ubuntu";
using var listener = new HttpListener();
listener.Prefixes.Add(Url);
listener.Start();
Console.WriteLine($"VLC URL: {Url}");

using var capture = new Process {
    StartInfo = new ProcessStartInfo("ssh") {
        UseShellExecute = false,
        RedirectStandardOutput = true,
        RedirectStandardError = true,
        CreateNoWindow = true,
    },
};
capture.StartInfo.ArgumentList.Add(sshTarget);
capture.StartInfo.ArgumentList.Add("sudo -n /usr/local/sbin/sc132gs-vlc-pattern-stream");
capture.Start();
using var stop = new CancellationTokenSource();
Console.CancelKeyPress += (_, e) => { e.Cancel = true; stop.Cancel(); };

var latest = new LatestFrame();
var errors = Task.Run(async () => {
    while (await capture.StandardError.ReadLineAsync(stop.Token) is { } line)
        Console.Error.WriteLine(line);
});
var server = Task.Run(async () => {
    while (!stop.IsCancellationRequested) {
        HttpListenerContext context;
        try { context = await listener.GetContextAsync().WaitAsync(stop.Token); }
        catch (OperationCanceledException) { break; }
        _ = Task.Run(() => ServeAsync(context, latest, stop.Token));
    }
});

try {
    var input = capture.StandardOutput.BaseStream;
    var header = new byte[HeaderBytes];
    var cam0 = new byte[RawBytes];
    var cam1 = new byte[RawBytes];
    var frameCount = 0;
    while (!stop.IsCancellationRequested) {
        await input.ReadExactlyAsync(header, stop.Token);
        if (!header.AsSpan(0, 8).SequenceEqual("S132PAIR"u8) ||
            BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(8, 4)) != 1 ||
            BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(12, 4)) != HeaderBytes ||
            BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(16, 4)) != RawBytes ||
            BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(20, 4)) != Width ||
            BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(24, 4)) != Height)
            throw new InvalidDataException("Unexpected paired RAW10 stream header.");
        await input.ReadExactlyAsync(cam0, stop.Token);
        await input.ReadExactlyAsync(cam1, stop.Token);
        latest.Publish(EncodeJpeg(cam0, cam1));
        if (++frameCount % 50 == 0)
            Console.WriteLine($"MJPEG frames encoded: {frameCount}");
    }
}
catch (OperationCanceledException) { }
catch (EndOfStreamException) {
    Console.Error.WriteLine("Camera stream ended.");
}
finally {
    stop.Cancel();
    listener.Stop();
    if (!capture.HasExited) capture.Kill(entireProcessTree: true);
    await capture.WaitForExitAsync();
    try { await Task.WhenAll(errors, server); } catch (OperationCanceledException) { }
}

static async Task ServeAsync(HttpListenerContext context, LatestFrame frames,
                             CancellationToken token) {
    try {
        context.Response.StatusCode = 200;
        context.Response.ContentType = "multipart/x-mixed-replace; boundary=frame";
        context.Response.SendChunked = true;
        var stream = context.Response.OutputStream;
        var seen = 0L;
        while (!token.IsCancellationRequested) {
            var (sequence, jpeg) = await frames.NextAsync(seen, token);
            seen = sequence;
            var prefix = Encoding.ASCII.GetBytes(
                $"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {jpeg.Length}\r\n\r\n");
            await stream.WriteAsync(prefix, token);
            await stream.WriteAsync(jpeg, token);
            await stream.WriteAsync("\r\n"u8.ToArray(), token);
            await stream.FlushAsync(token);
        }
    }
    catch (Exception ex) when (ex is IOException or HttpListenerException or
                               OperationCanceledException) { }
    finally { context.Response.Close(); }
}

static byte[] EncodeJpeg(byte[] cam0, byte[] cam1) {
    var gray0 = new byte[Width * Height];
    var gray1 = new byte[Width * Height];
    var hist0 = new int[256];
    var hist1 = new int[256];
    UnpackHighBytes(cam0, gray0, hist0);
    UnpackHighBytes(cam1, gray1, hist1);
    var low0 = Percentile(hist0, gray0.Length / 200);
    var high0 = Math.Max(low0 + 1, Percentile(hist0, gray0.Length * 995 / 1000));
    var low1 = Percentile(hist1, gray1.Length / 200);
    var high1 = Math.Max(low1 + 1, Percentile(hist1, gray1.Length * 995 / 1000));
    using var bitmap = new Bitmap(Width * 2, Height, PixelFormat.Format24bppRgb);
    var data = bitmap.LockBits(new Rectangle(0, 0, Width * 2, Height),
                               ImageLockMode.WriteOnly, PixelFormat.Format24bppRgb);
    try {
        var pixels = new byte[data.Stride * Height];
        Parallel.For(0, Height, y => {
            var source = y * Width;
            var destination = y * data.Stride;
            for (var x = 0; x < Width; ++x) {
                var a = Stretch(gray0[source + x], low0, high0);
                var b = Stretch(gray1[source + x], low1, high1);
                var p0 = destination + x * 3;
                var p1 = destination + (Width + x) * 3;
                pixels[p0] = pixels[p0 + 1] = pixels[p0 + 2] = a;
                pixels[p1] = pixels[p1 + 1] = pixels[p1 + 2] = b;
            }
        });
        Marshal.Copy(pixels, 0, data.Scan0, pixels.Length);
    }
    finally { bitmap.UnlockBits(data); }
    using var output = new MemoryStream();
    var encoder = ImageCodecInfo.GetImageEncoders().Single(x => x.MimeType == "image/jpeg");
    using var quality = new EncoderParameters(1);
    quality.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, 75L);
    bitmap.Save(output, encoder, quality);
    return output.ToArray();
}

static void UnpackHighBytes(byte[] raw, byte[] gray, int[] histogram) {
    var destination = 0;
    for (var source = 0; source < raw.Length; source += 5) {
        for (var i = 0; i < 4; ++i) {
            var value = raw[source + i];
            gray[destination++] = value;
            ++histogram[value];
        }
    }
}

static int Percentile(int[] histogram, int threshold) {
    var count = 0;
    for (var value = 0; value < histogram.Length; ++value) {
        count += histogram[value];
        if (count >= threshold) return value;
    }
    return 255;
}

static byte Stretch(byte value, int low, int high) =>
    (byte)Math.Clamp((value - low) * 255 / (high - low), 0, 255);

sealed class LatestFrame {
    private readonly object gate = new();
    private byte[]? jpeg;
    private long sequence;
    private TaskCompletionSource signal = NewSignal();

    public void Publish(byte[] bytes) {
        lock (gate) {
            jpeg = bytes;
            ++sequence;
            signal.TrySetResult();
            signal = NewSignal();
        }
    }

    public async Task<(long Sequence, byte[] Jpeg)> NextAsync(long seen,
                                                               CancellationToken token) {
        while (true) {
            Task wait;
            lock (gate) {
                if (sequence > seen && jpeg is not null) return (sequence, jpeg);
                wait = signal.Task;
            }
            await wait.WaitAsync(token);
        }
    }

    private static TaskCompletionSource NewSignal() =>
        new(TaskCreationOptions.RunContinuationsAsynchronously);
}
