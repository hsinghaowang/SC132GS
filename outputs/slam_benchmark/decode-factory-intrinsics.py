"""Decode only the identified UNION V1.2 layout; never substitute generic K."""
import hashlib
import json
import math
from pathlib import Path
import struct
import numpy as np

base=Path(__file__).resolve().parent
root=base/'factory-calibration-20261013'
probe=json.loads((root/'probe.json').read_text())
repeat=json.loads((root/'repeat-verification.json').read_text())
assert repeat['identical'] and repeat['saved_camera_state_unchanged']
blob=(root/'bus18-eeprom.bin').read_bytes()
assert blob==(root/'bus18-repeat.bin').read_bytes() and len(blob)==0x219
assert hashlib.sha256(blob).hexdigest()==repeat['sha256']
expected=b'UNION\0\0\0'+bytes((0x11,1,1,2,0,4,0))
assert blob[:15]==expected and blob[15]==sum(blob[:14])%255+1
def camera(offset,name,address,topic):
    fx,fy,cx,cy,*dist=struct.unpack_from('<8d',blob,offset)
    assert all(map(math.isfinite,(fx,fy,cx,cy,*dist)))
    assert 0<fx<10000 and 0<fy<10000 and 0<=cx<1088 and 0<=cy<1280
    return dict(factory_eye=name,sensor_I2C_address=address,rostopic=topic,
        camera_model='pinhole',distortion_model='equidistant',intrinsics=[fx,fy,cx,cy],
        K=[[fx,0.0,cx],[0.0,fy,cy],[0.0,0.0,1.0]],distortion_coeffs=dist,
        resolution=[1088,1280],resolution_source='official SDK raw sensor preset and current captured geometry, not inferred from K',
        factory_rotation_degrees=0,pixel_data_rotated_or_rectified=False)
# SDK preset: right sensor=0x32; current cam0 is bus18/0x32. Left=0x30, cam1=bus16.
cameras=dict(cam0=camera(0x81,'right','0x32','/cam0/image_raw'),cam1=camera(0x18,'left','0x30','/cam1/image_raw'))
stereo_R=np.array(struct.unpack_from('<9d',blob,0xea)).reshape(3,3)
stereo_T=np.array(struct.unpack_from('<3d',blob,0x132))
assert np.isfinite(stereo_R).all() and np.isfinite(stereo_T).all()
assert np.linalg.norm(stereo_R.T@stereo_R-np.eye(3))<1e-3 and abs(np.linalg.det(stereo_R)-1)<1e-3
result=dict(status='factory_intrinsics_read_and_decoded_not_geometrically_validated',
    vendor='UNION',version='1.2',EEPROM_bus=18,EEPROM_address='0x50',raw_sha256=repeat['sha256'],
    header_checksum_passed=True,repeat_reads_identical=True,saved_camera_state_unchanged=True,
    official_decoder_revision=probe['decoder_source_revision'],cameras=cameras,
    stereo_factory_raw=dict(rotation_left_to_right=stereo_R.tolist(),translation_left_to_right=stereo_T.tolist(),
                            translation_units='Not independently verified; preserved raw, not exported for live VIO yet'),
    geometric_validation_performed=False,physical_camera_IMU_time_synchronization_validated=False,
    note='Header checksum does not validate every calibration payload byte; repeated read plus finite/plausible values and rotation sanity are integrity checks, not reprojection validation.')
(root/'raw-intrinsics.json').write_text(json.dumps(result,indent=2))
parts=['# Actual module UNION V1.2 EEPROM RAW intrinsics; unrotated 1088x1280.',
       '# Intrinsics-only export: not a complete OpenVINS/Kalibr camera-IMU config.',
       '# cam0=right sensor0x32/bus18/video0; cam1=left sensor0x30/bus16/video3.',
       '# Fisheye/equidistant coefficients: k1,k2,k3,k4; do not use radtan.',
       '# Factory numeric decoding verified; reprojection/extrinsics/time validation pending.']
for name,cam in cameras.items():
    parts.extend([name+':','  camera_model: pinhole','  distortion_model: equidistant',
        '  resolution: [1088, 1280]','  intrinsics: '+json.dumps(cam['intrinsics']),
        '  distortion_coeffs: '+json.dumps(cam['distortion_coeffs']),'  rostopic: '+cam['rostopic']])
(root/'raw-intrinsics.yaml').write_text('\n'.join(parts)+'\n')
print(json.dumps(dict(cameras=cameras,stereo_T_raw=stereo_T.tolist()),indent=2))
