"""Generate isolated probe/module sources; do not edit the installed module."""
from pathlib import Path
import re
import urllib.request

root = Path(__file__).resolve().parent
source = (root / 'baseline-sc132gs.c').read_text()
source = source.replace('static bool hdr;', '''/* Experimental binning: sensor table is applied before STREAMON.
 * Does not alter the installed module on disk.
 */
static bool experimental_half_format;
module_param(experimental_half_format, bool, 0644);
MODULE_PARM_DESC(experimental_half_format, "Experimental 544x640 binning configured before stream-on");
static unsigned int experimental_fps = 120;
module_param(experimental_fps, uint, 0644);

static bool hdr;''')
source = source.replace('fse->min_width = fse->max_width = SC132GS_WIDTH;',
                        'fse->min_width = fse->max_width = experimental_half_format ? 544 : SC132GS_WIDTH;')
source = source.replace('fse->min_height = fse->max_height = SC132GS_HEIGHT;',
                        'fse->min_height = fse->max_height = experimental_half_format ? 640 : SC132GS_HEIGHT;')
source = source.replace('fmt->width = SC132GS_WIDTH;', 'fmt->width = experimental_half_format ? 544 : SC132GS_WIDTH;')
source = source.replace('fmt->height = SC132GS_HEIGHT;', 'fmt->height = experimental_half_format ? 640 : SC132GS_HEIGHT;')
(root / 'sc132gs.c').write_text(source)
(root / 'Makefile').write_text('obj-m += sc132gs.o\n')

probe = (root / 'baseline-single-rate-check.cpp').read_text()
probe = probe.replace('constexpr std::uint32_t kWidth = 1088;', 'std::uint32_t kWidth = 1088;')
probe = probe.replace('constexpr std::uint32_t kHeight = 1280;', 'std::uint32_t kHeight = 1280;\nstd::uint32_t kStride;\nstd::uint32_t saved_frames;')
probe = probe.replace('v4l2_requestbuffers request{};', 'kStride = format.fmt.pix_mp.plane_fmt[0].bytesperline;\n        std::cout << "stride=" << kStride << " width=" << kWidth << " height=" << kHeight << std::endl;\n        v4l2_requestbuffers request{};')
probe = probe.replace('if ((buffer.flags & V4L2_BUF_FLAG_ERROR) || plane.bytesused != 1740800)\n            throw std::runtime_error("invalid RAW10 payload or V4L2 error flag");', '''if ((buffer.flags & V4L2_BUF_FLAG_ERROR) || plane.bytesused < kStride*kHeight) {
            checked_ioctl(VIDIOC_QBUF, &buffer, "VIDIOC_QBUF(initial invalid)");
            return std::nullopt;
        }''')
probe = probe.replace('const Sample sample{buffer.sequence, timestamp_ns, checksum};', '''if (valid_frames_++ >= 120 && saved_frames < 32) {
            std::ofstream raw("frame-" + std::to_string(saved_frames++) + ".raw", std::ios::binary);
            raw.write(reinterpret_cast<const char*>(bytes), plane.bytesused);
        }
        const Sample sample{buffer.sequence, timestamp_ns, checksum};''')
probe = probe.replace('std::string path_;', 'unsigned valid_frames_{};\n    std::string path_;')
probe = probe.replace('if ((buffer.flags & V4L2_BUF_FLAG_ERROR) || plane.bytesused < kStride*kHeight) {', 'if ((buffer.flags & V4L2_BUF_FLAG_ERROR) || plane.bytesused < kStride*kHeight) {\n            if (invalid_frames_++ < 5) std::cerr << "invalid flags=" << buffer.flags << " bytes=" << plane.bytesused << " expected=" << kStride*kHeight << std::endl;')
probe = probe.replace('unsigned valid_frames_{};', 'unsigned valid_frames_{}; unsigned invalid_frames_{};')
probe = probe.replace('throw std::runtime_error("no valid frame or capture poll error");', 'throw std::runtime_error("no valid frame or capture poll error: ready=" + std::to_string(ready) + " revents=" + std::to_string(descriptor.revents));')
probe = probe.replace('if (argc != 3) throw std::invalid_argument("usage: single-rate-check CAMERA_NODE FRAMES");', '''if (argc != 5) throw std::invalid_argument("usage: raw-rate-check CAMERA_NODE FRAMES WIDTH HEIGHT");
        kWidth = parse_size(argv[3], "width");
        kHeight = parse_size(argv[4], "height");''')
probe = probe.replace('if (argc != 5)', 'if (argc != 6)')
probe = probe.replace('CaptureDevice camera(argv[1]);', 'CaptureDevice camera(argv[1]);\n        CaptureDevice other(argv[5]);')
probe = probe.replace('camera.prepare();\n        camera.start();', 'camera.prepare();\n        other.prepare();\n        camera.start();\n        other.start();')
probe = probe.replace('if (valid_frames_++ >= 120 && saved_frames < 32)', 'if (path_ == save_path && valid_frames_++ >= 120 && saved_frames < 32)')
probe = probe.replace('std::uint32_t saved_frames;', 'std::uint32_t saved_frames;\nstd::string save_path;')
probe = probe.replace('kWidth = parse_size(argv[3], "width");', 'save_path = argv[1];\n        kWidth = parse_size(argv[3], "width");')
probe = probe.replace('pollfd descriptor{camera.fd(), POLLIN, 0};\n            int ready = ::poll(&descriptor, 1, 10000);', 'pollfd descriptors[] = {{camera.fd(), POLLIN, 0}, {other.fd(), POLLIN, 0}};\n            int ready = ::poll(descriptors, 2, 10000);\n            auto& descriptor = descriptors[0];\n            if (descriptors[1].revents & POLLIN) (void)other.dequeue();')
probe = probe.replace('if (auto sample = camera.dequeue()) samples.push_back(*sample);', 'if (descriptor.revents & POLLIN) if (auto sample = camera.dequeue()) samples.push_back(*sample);')
(root / 'raw-rate-check.cpp').write_text(probe)

url = 'https://raw.githubusercontent.com/espressif/esp-video-components/master/esp_cam_sensor/sensors/sc132gs/private_include/sc132gs_mipi_2lane_24Minput_544x640_raw10_60fps.h'
table = urllib.request.urlopen(url).read().decode()
(root / 'espressif-544x640-60fps.h').write_text(table, encoding='utf-8')
registers = re.findall(r'\{(0x[0-9a-fA-F]{4}),\s*(0x[0-9a-fA-F]{2})\}', table)
(root / 'espressif-544x640-60fps.txt').write_text(''.join(f'{r} {v}\n' for r,v in registers))
# Vendor binning block kept intact; appended to the verified 120 FPS table.
# Both clock and exposure remain those of the non-binning comparison.
block = table[table.index('//hbin color'):table.index('{0x36e9, 0x23}')]
registers = re.findall(r'\{(0x[0-9a-fA-F]{4}),\s*(0x[0-9a-fA-F]{2})\}', block)
(root / 'binning-on-120-timing.txt').write_text(''.join(f'{r} {v}\n' for r,v in registers))

audit = root.parent / 'linear120-evidence-20261007/profile-audit'
full_regs = []
for filename in ('kendryte-120-registers.txt', 'gs130wi-geometry-short-exposure.txt'):
    full_regs += [tuple(line.split()) for line in (audit/filename).read_text().splitlines() if line.strip()]
bin_regs = registers
vendor_regs = re.findall(r'\{(0x[0-9a-fA-F]{4}),\s*(0x[0-9a-fA-F]{2})\}', table)
vendor_regs += [('0x3e00','0x00'),('0x3e01','0x10'),('0x3e02','0x00'),('0x3e08','0x03'),('0x3e09','0x20')]
def array(name, regs):
    return 'static const struct sc132gs_reg '+name+'[] = {\n'+''.join('    {'+r+', '+v+'},\n' for r,v in regs)+'};\n'
extra = array('experimental_bin120', full_regs+bin_regs) + array('experimental_bin60', vendor_regs)
extra += '''
static int sc132gs_write_experimental_binning(struct sc132gs *sensor)
{
    const struct sc132gs_reg *regs = experimental_fps == 60 ? experimental_bin60 : experimental_bin120;
    size_t count = experimental_fps == 60 ? ARRAY_SIZE(experimental_bin60) : ARRAY_SIZE(experimental_bin120);
    size_t i;
    unsigned int value;
    int ret;
    if (sensor->hdr_mode || (experimental_fps != 60 && experimental_fps != 120))
        return -EINVAL;
    /* All writes occur while the sensor is in standby. Never emit a full
     * frame into the half-sized DMA buffer, including during startup. */
    for (i=0; i<count; ++i) {
        ret = regmap_write(sensor->regmap, regs[i].address, regs[i].value);
        if (ret) return ret;
        if (regs[i].address == 0x0103) usleep_range(10000, 11000);
    }
    ret = regmap_read(sensor->regmap, 0x0100, &value);
    if (ret || value != 0) return ret ? ret : -EIO;
    for (i=0; i<4; ++i) {
        static const u8 expected[] = {0x02, 0x20, 0x02, 0x80};
        ret = regmap_read(sensor->regmap, 0x3208+i, &value);
        if (ret || value != expected[i]) return ret ? ret : -EIO;
    }
    dev_info(sensor->dev, "experimental binning configured before stream-on, requested %u FPS\\n", experimental_fps);
    return 0;
}
'''
source = source.replace('static int sc132gs_s_stream(', extra+'\nstatic int sc132gs_s_stream(')
source = source.replace('\t\tif (!ret) {\n\t\t\tret = regmap_write(sensor->regmap, SC132GS_REG_CTRL_MODE,', '\t\tif (!ret && experimental_half_format)\n\t\t\tret = sc132gs_write_experimental_binning(sensor);\n\t\tif (!ret) {\n\t\t\tret = regmap_write(sensor->regmap, SC132GS_REG_CTRL_MODE,')
(root / 'sc132gs.c').write_text(source)
