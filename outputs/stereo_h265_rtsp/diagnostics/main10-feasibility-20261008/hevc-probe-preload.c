#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdarg.h>
#include <string.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <linux/videodev2.h>

/* Diagnostic-only workaround: select HEVC before enumerating raw encoder
 * formats. Use in an isolated process, never in the production service. */
int ioctl(int fd, unsigned long request, ...) {
    static int (*real_ioctl)(int, unsigned long, ...);
    if (!real_ioctl) real_ioctl = dlsym(RTLD_NEXT, "ioctl");
    va_list args;
    va_start(args, request);
    void *arg = va_arg(args, void *);
    va_end(args);
    if (request == VIDIOC_QUERYCAP && arg) {
        int result = real_ioctl(fd, request, arg);
        struct v4l2_capability *cap = arg;
        struct v4l2_format fmt = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE};
        if (result == 0 && strstr((char *)cap->card, "encoder") &&
            real_ioctl(fd, VIDIOC_G_FMT, &fmt) == 0 &&
            fmt.fmt.pix_mp.pixelformat != V4L2_PIX_FMT_HEVC) {
            fmt.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_HEVC;
            fprintf(stderr, "diagnostic HEVC-at-querycap: rc=%d\n",
                real_ioctl(fd, VIDIOC_S_FMT, &fmt));
        }
        return result;
    }
    if (request == VIDIOC_ENUM_FMT && arg &&
        ((struct v4l2_fmtdesc *)arg)->type == V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE) {
        struct v4l2_capability cap = {0};
        struct v4l2_format fmt = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE};
        if (real_ioctl(fd, VIDIOC_QUERYCAP, &cap) == 0 &&
            strstr((char *)cap.card, "encoder") &&
            real_ioctl(fd, VIDIOC_G_FMT, &fmt) == 0 &&
            fmt.fmt.pix_mp.pixelformat != V4L2_PIX_FMT_HEVC) {
            fmt.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_HEVC;
            int rc = real_ioctl(fd, VIDIOC_S_FMT, &fmt);
            fprintf(stderr, "diagnostic HEVC-before-enumeration: rc=%d\n", rc);
        }
    }
    return real_ioctl(fd, request, arg);
}
