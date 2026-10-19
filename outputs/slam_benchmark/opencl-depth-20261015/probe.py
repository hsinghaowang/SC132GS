"""Read-only board inventory; run through SSH stdin without shell-quoting source."""
import ctypes as c
import json
import subprocess

lib = c.CDLL('libOpenCL.so')
uint = c.c_uint
handle = c.c_void_p
lib.clGetPlatformIDs.argtypes = [uint, c.POINTER(handle), c.POINTER(uint)]
lib.clGetDeviceIDs.argtypes = [handle, c.c_ulong, uint, c.POINTER(handle), c.POINTER(uint)]
lib.clGetDeviceInfo.argtypes = [handle, uint, c.c_size_t, handle, c.POINTER(c.c_size_t)]
n = uint()
error = lib.clGetPlatformIDs(0, None, c.byref(n))
result = dict(platform_error=error, platforms=[])
platforms = (handle*n.value)()
if error == 0:
    lib.clGetPlatformIDs(n, platforms, None)
    for platform in platforms:
        count = uint()
        error = lib.clGetDeviceIDs(platform, 4, 0, None, c.byref(count))
        devices = (handle*count.value)()
        if error == 0:
            lib.clGetDeviceIDs(platform, 4, count, devices, None)
        items = []
        for device in devices:
            info = {}
            for name, key in [('name', 0x102B), ('vendor', 0x102C), ('driver', 0x102D),
                              ('version', 0x102F), ('extensions', 0x1030)]:
                size = c.c_size_t()
                lib.clGetDeviceInfo(device, key, 0, None, c.byref(size))
                buffer = c.create_string_buffer(size.value)
                lib.clGetDeviceInfo(device, key, size, buffer, None)
                info[name] = buffer.value.decode()
            items.append(info)
        result['platforms'].append(dict(gpu_error=error, gpu_devices=items))
for name, command in [('service', ['systemctl', 'show', 'sc132gs-camera-rtsp', '-p', 'ActiveState', '-p', 'MainPID']),
                      ('settings_hash', ['sudo', '-n', 'sha256sum', '/var/lib/sc132gs-camera/settings.yaml'])]:
    run = subprocess.run(command, capture_output=True, text=True, timeout=5)
    result[name] = dict(returncode=run.returncode, stdout=run.stdout.strip(), stderr=run.stderr.strip())
print(json.dumps(result, indent=2))
