using System.Buffers.Binary;
using System.Diagnostics;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

namespace Sc132gsLiveViewer;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new SynchronizedLiveViewForm(
            args.Length > 0 ? args[0] : "ubuntu@pi-ubuntu"));
    }
}

internal sealed class SynchronizedLiveViewForm : Form
{
    private const int WidthPixels = 1088;
    private const int HeightPixels = 1280;
    private const int RawStride = 1360;
    private const int FrameBytes = RawStride * HeightPixels;
    private const int HeaderBytes = 64;
    private const int PreviewPairStep = 3;
    private const int MaximumPairDeltaUs = 1000;

    private sealed record PairedPreview(
        Bitmap Image,
        ulong PairIndex,
        uint Cam0Sequence,
        uint Cam1Sequence,
        long Cam0TimestampNs,
        long Cam1TimestampNs);

    private readonly PictureBox pairedPicture = new()
    {
        BackColor = Color.Black,
        Dock = DockStyle.Fill,
        SizeMode = PictureBoxSizeMode.Zoom
    };
    private readonly ToolStripStatusLabel status = new("等待啟動…")
    {
        Spring = true,
        TextAlign = ContentAlignment.MiddleLeft
    };
    private readonly System.Windows.Forms.Timer displayTimer = new() { Interval = 16 };
    private readonly CancellationTokenSource stop = new();
    private readonly Stopwatch elapsed = Stopwatch.StartNew();
    private readonly string sshTarget;
    private Process? setupSsh;
    private Process? captureSsh;
    private PairedPreview? pendingPair;
    private long receivedPairs;
    private long displayedPairs;

    public SynchronizedLiveViewForm(string sshTarget)
    {
        this.sshTarget = sshTarget;
        Text = $"SC132GS 雙目同步 RAW10 — {sshTarget}";
        ClientSize = new Size(1400, 800);
        MinimumSize = new Size(800, 520);

        var title = new Label
        {
            AutoSize = false,
            Dock = DockStyle.Top,
            Font = new Font("Segoe UI", 12, FontStyle.Bold),
            Height = 36,
            Text = "CAM0 · SC132GS I²C 0x32                  " +
                   "CAM1 · SC132GS I²C 0x30",
            TextAlign = ContentAlignment.MiddleCenter
        };
        var statusStrip = new StatusStrip { SizingGrip = false };
        statusStrip.Items.Add(status);
        Controls.Add(pairedPicture);
        Controls.Add(statusStrip);
        Controls.Add(title);

        Shown += async (_, _) => await StartCaptureAsync();
        FormClosing += (_, _) => StopCapture();
        displayTimer.Tick += (_, _) => DisplayLatestPair();
        displayTimer.Start();
    }

    private async Task StartCaptureAsync()
    {
        status.Text = "設定雙目 V4L2 pipeline…";
        const string setupCommand =
            "sudo -n modprobe qcom_camss && " +
            "for n in $(seq 1 20); do ls /dev/media[0-9]* >/dev/null 2>&1 && break; sleep 0.25; done; " +
            "sudo -n /usr/local/sbin/configure-sc132gs-dual-pipeline";

        try
        {
            var (exitCode, error) = await RunSetupAsync(setupCommand, stop.Token);
            if (exitCode != 0)
            {
                status.Text = $"設定失敗：{LastUsefulLine(error)}";
                return;
            }

            StartPairedCapture();
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            status.Text = $"啟動失敗：{ex.Message}";
        }
    }

    private async Task<(int ExitCode, string Error)> RunSetupAsync(
        string command,
        CancellationToken token)
    {
        setupSsh = CreateSshProcess(command);
        setupSsh.Start();
        var outputTask = setupSsh.StandardOutput.ReadToEndAsync(token);
        var errorTask = setupSsh.StandardError.ReadToEndAsync(token);
        await setupSsh.WaitForExitAsync(token);
        _ = await outputTask;
        return (setupSsh.ExitCode, await errorTask);
    }

    private void StartPairedCapture()
    {
        var command =
            "cams=$(sudo -n /usr/local/sbin/sc132gs-discover pair) && " +
            "sudo -n /usr/local/bin/sc132gs-paired-stream " +
            $"$cams {PreviewPairStep} {MaximumPairDeltaUs}";
        captureSsh = CreateSshProcess(command);
        captureSsh.Start();
        status.Text = "等待第一組 timestamp-matched frame pair…";
        _ = Task.Run(() => DrainErrorsAsync(captureSsh.StandardError, stop.Token));
        _ = Task.Run(() => CaptureLoopAsync(captureSsh.StandardOutput.BaseStream, stop.Token));
    }

    private Process CreateSshProcess(string command)
    {
        var process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = "ssh",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            }
        };
        process.StartInfo.ArgumentList.Add(sshTarget);
        process.StartInfo.ArgumentList.Add(command);
        return process;
    }

    private async Task CaptureLoopAsync(Stream input, CancellationToken token)
    {
        try
        {
            var header = new byte[HeaderBytes];
            while (!token.IsCancellationRequested)
            {
                await ReadExactlyAsync(input, header, token);
                var metadata = ParseHeader(header);

                var cam0 = new byte[FrameBytes];
                var cam1 = new byte[FrameBytes];
                await ReadExactlyAsync(input, cam0, token);
                await ReadExactlyAsync(input, cam1, token);

                var bitmap = DecodePairedRaw10(cam0, cam1);
                var preview = new PairedPreview(
                    bitmap,
                    metadata.PairIndex,
                    metadata.Cam0Sequence,
                    metadata.Cam1Sequence,
                    metadata.Cam0TimestampNs,
                    metadata.Cam1TimestampNs);
                var replaced = Interlocked.Exchange(ref pendingPair, preview);
                replaced?.Image.Dispose();
                Interlocked.Increment(ref receivedPairs);
            }
        }
        catch (OperationCanceledException) { }
        catch (EndOfStreamException)
        {
            UpdateStatus("配對串流已停止");
        }
        catch (Exception ex)
        {
            UpdateStatus($"配對串流錯誤：{ex.Message}");
        }
    }

    private static async Task ReadExactlyAsync(
        Stream input,
        byte[] buffer,
        CancellationToken token)
    {
        var offset = 0;
        while (offset < buffer.Length)
        {
            var count = await input.ReadAsync(buffer.AsMemory(offset), token);
            if (count == 0)
                throw new EndOfStreamException();
            offset += count;
        }
    }

    private readonly record struct PairMetadata(
        ulong PairIndex,
        uint Cam0Sequence,
        uint Cam1Sequence,
        long Cam0TimestampNs,
        long Cam1TimestampNs);

    private static PairMetadata ParseHeader(byte[] header)
    {
        if (!header.AsSpan(0, 8).SequenceEqual("S132PAIR"u8))
            throw new InvalidDataException("paired stream magic 不正確");

        var version = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(8, 4));
        var headerBytes = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(12, 4));
        var frameBytes = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(16, 4));
        var width = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(20, 4));
        var height = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(24, 4));
        if (version != 1 || headerBytes != HeaderBytes || frameBytes != FrameBytes ||
            width != WidthPixels || height != HeightPixels)
        {
            throw new InvalidDataException(
                $"paired stream format 不符：v{version} {width}x{height} bytes={frameBytes}");
        }

        return new PairMetadata(
            BinaryPrimitives.ReadUInt64LittleEndian(header.AsSpan(32, 8)),
            BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(56, 4)),
            BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(60, 4)),
            BinaryPrimitives.ReadInt64LittleEndian(header.AsSpan(40, 8)),
            BinaryPrimitives.ReadInt64LittleEndian(header.AsSpan(48, 8)));
    }

    private async Task DrainErrorsAsync(StreamReader error, CancellationToken token)
    {
        try
        {
            while (!token.IsCancellationRequested &&
                   await error.ReadLineAsync(token) is { } line)
            {
                if (line.Length > 0 && line[0] != '<')
                    Debug.WriteLine($"paired-stream: {line}");
            }
        }
        catch (OperationCanceledException) { }
    }

    private void DisplayLatestPair()
    {
        var preview = Interlocked.Exchange(ref pendingPair, null);
        if (preview is null)
            return;

        var old = pairedPicture.Image;
        pairedPicture.Image = preview.Image;
        old?.Dispose();

        var shown = Interlocked.Increment(ref displayedPairs);
        var seconds = Math.Max(0.1, elapsed.Elapsed.TotalSeconds);
        var deltaUs =
            (preview.Cam1TimestampNs - preview.Cam0TimestampNs) / 1000.0;
        status.Text =
            $"Pair {preview.PairIndex}｜seq {preview.Cam0Sequence}/{preview.Cam1Sequence}" +
            $"｜Δtimestamp {deltaUs:+0.0;-0.0;0.0} µs" +
            $"｜接收 {receivedPairs / seconds:F1} pair/s" +
            $"｜顯示 {shown / seconds:F1} pair/s｜單次合成呈現";
    }

    private static Bitmap DecodePairedRaw10(byte[] cam0Raw, byte[] cam1Raw)
    {
        var cam0Gray = new ushort[WidthPixels * HeightPixels];
        var cam1Gray = new ushort[WidthPixels * HeightPixels];
        var cam0Histogram = new int[1024];
        var cam1Histogram = new int[1024];

        Parallel.Invoke(
            () => UnpackRaw10(cam0Raw, cam0Gray, cam0Histogram),
            () => UnpackRaw10(cam1Raw, cam1Gray, cam1Histogram));

        var cam0Low = Percentile(cam0Histogram, cam0Gray.Length / 200);
        var cam0High = Percentile(cam0Histogram, cam0Gray.Length * 995 / 1000);
        var cam1Low = Percentile(cam1Histogram, cam1Gray.Length / 200);
        var cam1High = Percentile(cam1Histogram, cam1Gray.Length * 995 / 1000);
        cam0High = Math.Max(cam0Low + 1, cam0High);
        cam1High = Math.Max(cam1Low + 1, cam1High);

        var compositeWidth = WidthPixels * 2;
        var bitmap = new Bitmap(compositeWidth, HeightPixels, PixelFormat.Format32bppArgb);
        var data = bitmap.LockBits(
            new Rectangle(0, 0, compositeWidth, HeightPixels),
            ImageLockMode.WriteOnly,
            PixelFormat.Format32bppArgb);
        try
        {
            var pixels = new byte[data.Stride * HeightPixels];
            Parallel.For(0, HeightPixels, y =>
            {
                var sourceRow = y * WidthPixels;
                var destinationRow = y * data.Stride;
                for (var x = 0; x < WidthPixels; ++x)
                {
                    WriteGrayPixel(
                        pixels,
                        destinationRow + x * 4,
                        Stretch(cam0Gray[sourceRow + x], cam0Low, cam0High));
                    WriteGrayPixel(
                        pixels,
                        destinationRow + (WidthPixels + x) * 4,
                        Stretch(cam1Gray[sourceRow + x], cam1Low, cam1High));
                }
            });
            Marshal.Copy(pixels, 0, data.Scan0, pixels.Length);
        }
        finally
        {
            bitmap.UnlockBits(data);
        }

        using var graphics = Graphics.FromImage(bitmap);
        graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using var divider = new Pen(Color.White, 3);
        graphics.DrawLine(divider, WidthPixels, 0, WidthPixels, HeightPixels);
        return bitmap;
    }

    private static void UnpackRaw10(byte[] raw, ushort[] gray, int[] histogram)
    {
        var source = 0;
        var target = 0;
        while (source + 4 < raw.Length && target + 3 < gray.Length)
        {
            var b0 = raw[source++];
            var b1 = raw[source++];
            var b2 = raw[source++];
            var b3 = raw[source++];
            var low = raw[source++];
            var p0 = (b0 << 2) | (low & 0x03);
            var p1 = (b1 << 2) | ((low >> 2) & 0x03);
            var p2 = (b2 << 2) | ((low >> 4) & 0x03);
            var p3 = (b3 << 2) | ((low >> 6) & 0x03);
            gray[target++] = (ushort)p0;
            gray[target++] = (ushort)p1;
            gray[target++] = (ushort)p2;
            gray[target++] = (ushort)p3;
            histogram[p0]++;
            histogram[p1]++;
            histogram[p2]++;
            histogram[p3]++;
        }
    }

    private static int Percentile(int[] histogram, int threshold)
    {
        var sum = 0;
        for (var i = 0; i < histogram.Length; ++i)
        {
            sum += histogram[i];
            if (sum >= threshold)
                return i;
        }
        return histogram.Length - 1;
    }

    private static byte Stretch(ushort value, int low, int high) =>
        (byte)Math.Clamp((value - low) * 255 / (high - low), 0, 255);

    private static void WriteGrayPixel(byte[] pixels, int destination, byte value)
    {
        pixels[destination] = value;
        pixels[destination + 1] = value;
        pixels[destination + 2] = value;
        pixels[destination + 3] = 255;
    }

    private void UpdateStatus(string text)
    {
        if (!IsDisposed && IsHandleCreated)
            BeginInvoke(() => status.Text = text);
    }

    private static string LastUsefulLine(string text) =>
        text.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
            .LastOrDefault() ?? "未知錯誤";

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (keyData == Keys.Escape)
        {
            Close();
            return true;
        }
        return base.ProcessCmdKey(ref msg, keyData);
    }

    private void StopCapture()
    {
        displayTimer.Stop();
        stop.Cancel();
        Kill(setupSsh);
        Kill(captureSsh);
        Interlocked.Exchange(ref pendingPair, null)?.Image.Dispose();
        pairedPicture.Image?.Dispose();
    }

    private static void Kill(Process? process)
    {
        try
        {
            if (process is { HasExited: false })
                process.Kill(entireProcessTree: true);
        }
        catch { }
    }
}
