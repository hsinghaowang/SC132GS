#!/usr/bin/env python3
"""Read-only mapping of live device-tree stream IDs and capture allocation sizes."""
import json
from pathlib import Path
import struct
import subprocess

def words(path):
    data=path.read_bytes()
    return [hex(value) for value in struct.unpack('>'+str(len(data)//4)+'I',data)] if len(data)%4==0 else dict(hex=data.hex())

def main():
    root=Path('/sys/firmware/devicetree/base')
    entries=[]
    for name in ('iommus','qcom,stream-id','qcom,stream-id-mask','qcom,iommu-context-bank'):
        for prop in root.rglob(name):
            values=words(prop)
            node=prop.parent
            if isinstance(values,list) and ('0x8a0' in values or any(s in str(node) for s in ('camss','video-codec','cam_smmu'))):
                status=(node/'status').read_bytes().rstrip(b'\0').decode() if (node/'status').exists() else 'okay (default)'
                entry=dict(node=str(node.relative_to(root)),property=name,values=values,status=status)
                if name=='iommus' and len(values)%3==0:
                    entry['stream_matches']=[dict(stream_id=values[i+1],mask=values[i+2],
                        matches_fault=((int(values[i+1],16)^0x8a0)&~int(values[i+2],16))==0)
                        for i in range(0,len(values),3)]
                entries.append(entry)
    nodes={}
    for prop in root.rglob('phandle'):
        if prop.read_bytes() in [struct.pack('>I',int(entry['values'][0],16)) for entry in entries if isinstance(entry['values'],list) and entry['property']=='iommus']:
            nodes[words(prop)[0]]=str(prop.parent.relative_to(root))
    captures=[]
    for eye in ('cam0','cam1'):
        node=subprocess.check_output(['/usr/local/sbin/sc132gs-discover',eye],text=True).strip()
        info=subprocess.run(['v4l2-ctl','-d',node,'--get-fmt-video'],capture_output=True,text=True)
        captures.append(dict(eye=eye,node=node,returncode=info.returncode,format=info.stdout,error=info.stderr))
    faults=[0xfe1a9000,0xfefa9000]
    devices=[]
    for node in Path('/sys/bus/platform/devices').glob('*camss'):
        devices.append(dict(device=node.name,driver=str((node/'driver').resolve()),
            iommu_group=str((node/'iommu_group').resolve())))
    result=dict(stream_id_hex='0x8a0',matches=entries,phandle_nodes=nodes,captures=captures,
        camera_platform_devices=devices,
        raw10_payload_bytes=1088*1280*10//8,raw10_payload_hex=hex(1088*1280*10//8),
        fault_addresses=[dict(iova=hex(value),offset_within_2MiB=hex(value%(2*1024*1024))) for value in faults],
        note='Equal offsets suggest a buffer boundary; allocation base and write size still require verification.')
    print(json.dumps(result,indent=2))
if __name__=='__main__': main()
