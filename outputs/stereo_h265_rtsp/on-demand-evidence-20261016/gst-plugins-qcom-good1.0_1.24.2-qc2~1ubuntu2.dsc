-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA512

Format: 3.0 (quilt)
Source: gst-plugins-qcom-good1.0
Binary: gstreamer1.0-pulseaudio, gstreamer1.0-qt5, gstreamer1.0-qt6, gstreamer1.0-gtk3, gstreamer1.0-plugins-good, gstreamer1.0-plugins-qcom-good, libgstreamer-plugins-good1.0-0, libgstreamer-plugins-good1.0-dev
Architecture: any
Version: 1.24.2-qc2~1ubuntu2
Maintainer: Ubuntu Developers <ubuntu-devel-discuss@lists.ubuntu.com>
Uploaders: Sebastian Dröge <slomo@debian.org>, Sjoerd Simons <sjoerd@debian.org>, Marc Leeman <marc.leeman@gmail.com>,
Homepage: https://gstreamer.freedesktop.org
Standards-Version: 4.6.2
Vcs-Browser: https://salsa.debian.org/gstreamer-team/gst-plugins-good1.0/
Vcs-Git: https://salsa.debian.org/gstreamer-team/gst-plugins-good1.0.git
Build-Depends: debhelper, debhelper-compat (= 13), dpkg-dev (>= 1.15.1), meson (>= 0.62), pkgconf (>= 0.11.0), xvfb, xauth, libgirepository1.0-dev, libglib2.0-dev (>= 2.62), libgstreamer1.0-dev (>= 1.24.0), libgstreamer-plugins-qcom-base1.0-dev (>= 1.24.0), gstreamer1.0-plugins-base (>= 1.24.0), liborc-0.4-dev (>= 1:0.4.17), libcairo2-dev (>= 1.10.0), libcaca-dev, libspeex-dev (>= 1.1.6), libpng-dev, libshout-dev, libjpeg-dev, libaa1-dev (>= 1.4p5), libflac-dev (>= 1.1.4), libdv4-dev | libdv-dev, libxdamage-dev, libxext-dev, libxfixes-dev, libxml2-dev, libxv-dev, libx11-xcb-dev, libgtk-3-dev (>= 3.15), libtag1-dev (>= 1.5), libwavpack-dev (>= 4.60), libpulse-dev (>= 2.0), libbz2-dev, libjack-jackd2-dev, libvpx-dev (>= 1.7), libmp3lame-dev, libmpg123-dev (>= 1.13), libtwolame-dev (>= 0.3.10), libopencore-amrnb-dev, libopencore-amrwb-dev, qtbase5-dev [amd64 arm64 armel armhf i386 mips64el ppc64el riscv64 s390x hurd-i386 powerpc ppc64 sparc64], qtbase5-private-dev [amd64 arm64 armel armhf i386 mips64el ppc64el riscv64 s390x hurd-i386 powerpc ppc64 sparc64], qtdeclarative5-dev [amd64 arm64 armel armhf i386 mips64el ppc64el riscv64 s390x hurd-i386 powerpc ppc64 sparc64], qttools5-dev [amd64 arm64 armel armhf i386 mips64el ppc64el riscv64 s390x hurd-i386 powerpc ppc64 sparc64], qt6-base-private-dev [amd64 arm64 armel armhf mips64el ppc64el riscv64 s390x hurd-i386 powerpc ppc64 sparc64], qt6-declarative-dev [amd64 arm64 armel armhf mips64el ppc64el riscv64 s390x hurd-i386 powerpc ppc64 sparc64], qt6-shader-baker [amd64 arm64 armel armhf mips64el ppc64el riscv64 s390x powerpc ppc64 sparc64], qt6-tools-dev [amd64 arm64 armel armhf mips64el ppc64el riscv64 s390x hurd-i386 powerpc ppc64 sparc64], qt6-wayland-dev [amd64 arm64 armel armhf mips64el ppc64el riscv64 s390x powerpc ppc64 sparc64], libqt5x11extras5-dev [amd64 arm64 armel armhf i386 mips64el ppc64el riscv64 s390x hurd-i386 powerpc ppc64 sparc64], libqt5waylandclient5-dev [amd64 arm64 armel armhf mips64el ppc64el riscv64 s390x powerpc ppc64 sparc64], libraw1394-dev (>= 2.0.0) [linux-any], libiec61883-dev (>= 1.0.0) [linux-any], libavc1394-dev [linux-any], libv4l-dev [linux-any], libgudev-1.0-dev (>= 147) [linux-any], nasm (>= 2.13) [any-amd64]
Package-List:
 gstreamer1.0-gtk3 deb graphics optional arch=any
 gstreamer1.0-plugins-good deb libs optional arch=any
 gstreamer1.0-plugins-qcom-good deb libs optional arch=any
 gstreamer1.0-pulseaudio deb oldlibs optional arch=any
 gstreamer1.0-qt5 deb graphics optional arch=amd64,arm64,armel,armhf,i386,mips64el,ppc64el,riscv64,s390x,hurd-i386,powerpc,ppc64,sparc64
 gstreamer1.0-qt6 deb graphics optional arch=amd64,arm64,armel,armhf,mips64el,ppc64el,riscv64,s390x,hurd-i386,powerpc,ppc64,sparc64
 libgstreamer-plugins-good1.0-0 deb libs optional arch=any
 libgstreamer-plugins-good1.0-dev deb libdevel optional arch=any
Checksums-Sha1:
 b0d18aa3d09b3395f1414065cf62a708500c67dc 4317630 gst-plugins-qcom-good1.0_1.24.2.orig.tar.gz
 a1742c8e413f11619c9b48cb53bcc37126aa11b0 130820 gst-plugins-qcom-good1.0_1.24.2-qc2~1ubuntu2.debian.tar.xz
Checksums-Sha256:
 23daec8eaba9bcc39106afd2b591c4abe1d9076846d082fbced4656ac7c5f6fe 4317630 gst-plugins-qcom-good1.0_1.24.2.orig.tar.gz
 79492dc814a165b3cdbf8643fe40c38e4a5cb83c9da9bafa56a6a7a1adaa6e80 130820 gst-plugins-qcom-good1.0_1.24.2-qc2~1ubuntu2.debian.tar.xz
Files:
 7b8eeeb93246fd48415a79178a4c2160 4317630 gst-plugins-qcom-good1.0_1.24.2.orig.tar.gz
 1d7e84e7a9fbb2ac3f4869606d9beb00 130820 gst-plugins-qcom-good1.0_1.24.2-qc2~1ubuntu2.debian.tar.xz
Original-Maintainer: Maintainers of GStreamer packages <gst-plugins-good1.0@packages.debian.org>

-----BEGIN PGP SIGNATURE-----

iQJQBAEBCgA6FiEEfkZYUb8Fl/JsXBGMwiL31hNIef0FAmknFGAcHG1pY2hhZWwu
YmxhbmNAY2Fub25pY2FsLmNvbQAKCRDCIvfWE0h5/ZJnD/wLGsaYJsvQCcGsxEci
xczeFadcQkC+GvFOZm+auyx7DnxJjNoKniGsj1ihl3WjH6jWJnUF3Iou5LsCQOuT
iWAOWmcIrxOp7WeH2a4wa18MJO12AxHdPSdUTUCjHBdc4ay5WiIOUACQjjc4GgeX
lYZ8evfHNS/b7rXHRrM5kliJGlTJiWKWxl6MwxwXDB115V3euatps0/ere6UVmyg
Y856q8y1Gt6Y+CPqdWb30l6/qzQCMU98yHFbigcBulMUV6NcTnHpA7PsD1DiOkc0
waBZdxT33BAS6z59jy3Rqa42WAaOBf1LNTNUsBjdPZqph39kcKPSgiNRmYUo5kM3
0z57yLJLDcoDZD9pFMFXe8z5M0WzvuANlv533HtKEd01at+xz5DSQKz0YFRW34JF
JEyS9mGty7c3nzvshOyaW409qs1aU5pmO0AGrrW+J/JYurqW7jwENX1x2VMG+pYA
PG/0CZfSDYkKpzBROXn1tX6viJZ5P8Yh29IcjKydqzYyyhq1vw0nTAWb9Ej0yeAr
8uWfBCOC2q7drq0QQaB9G8XeBsvSPPo+LEJguVIaDIgOVn4JyhwuccsT5ggDAE7h
Q5xMu8e5RoDJNasjCNeJObOCL4dUEZc4mBE9Ww0Gc8FwzKTi2zcqf49K/atFLltc
sVzu9h51FVadJfON2MFfhWJ65A==
=FCiR
-----END PGP SIGNATURE-----
