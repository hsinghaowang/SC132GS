"""Read-only /proc/sysfs sampling; one-second process CPU deltas, not lifetime %CPU."""
import argparse
import json
import os
import signal
import time
from pathlib import Path

stopping=False
def stop(signum, frame):
    global stopping
    stopping=True

def processes():
    result={}
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            line=path.read_text();prefix,fields=line.rsplit(')',1);fields=fields.split()
            result[int(path.parent.name)]={'comm':prefix.split('(',1)[1],'state':fields[0],'ticks':int(fields[11])+int(fields[12]),'start_ticks':int(fields[19]),'rss_kib':int(fields[21])*os.sysconf('SC_PAGE_SIZE')/1024}
        except (OSError,ValueError,IndexError):pass
    return result

def platform():
    cpu={}
    for line in Path('/proc/stat').read_text().splitlines():
        if line.startswith('cpu'):
            fields=line.split();values=list(map(int,fields[1:9]));cpu[fields[0]]={'total':sum(values),'idle':values[3]+values[4]}
    clocks={}
    for path in Path('/sys/devices/system/cpu').glob('cpu[0-9]*/cpufreq'):
        value={}
        for key in ('scaling_cur_freq','scaling_governor'):
            try:value[key]=path.joinpath(key).read_text().strip()
            except OSError:pass
        clocks[path.parent.name]=value
    thermal={}
    for path in Path('/sys/class/thermal').glob('thermal_zone*'):
        try:thermal[path.name]={'type':(path/'type').read_text().strip(),'temperature_raw':(path/'temp').read_text().strip()}
        except OSError:pass
    mem={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.split(':',1)[0] in ('MemTotal','MemAvailable','SwapTotal','SwapFree'):
            key,value=line.split(':',1);mem[key]=value.strip()
    return cpu,clocks,thermal,mem

def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('--seconds',type=float,default=0)
    args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists():raise RuntimeError('refuse to overwrite existing load evidence')
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    ticks=os.sysconf('SC_CLK_TCK');start=time.monotonic();previous_time=start
    previous=processes();previous_cpu=platform()[0]
    with args.output.open('w') as file:
        while not stopping and (not args.seconds or time.monotonic()-start<args.seconds):
            time.sleep(1);now=time.monotonic();current=processes();cpu,clocks,thermal,mem=platform()
            elapsed=now-previous_time;busy=[]
            for pid,value in current.items():
                prior=previous.get(pid)
                if prior and prior['start_ticks']==value['start_ticks']:
                    value['cpu_percent_one_core']=100*(value['ticks']-prior['ticks'])/ticks/elapsed
                    if value['cpu_percent_one_core']>.1 or any(word in value['comm'] for word in ('stereo','fsync','ros_replay','python','cc1','ninja','make')):
                        busy.append(dict(pid=pid,**value))
            utilization={}
            for key,value in cpu.items():
                prior=previous_cpu.get(key)
                if prior:
                    total=value['total']-prior['total'];idle=value['idle']-prior['idle']
                    utilization[key]=100*(total-idle)/total if total else None
            file.write(json.dumps({'monotonic_ns':time.monotonic_ns(),'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'interval_s':elapsed,'cpu_busy_percent':utilization,'processes':sorted(busy,key=lambda x:x['cpu_percent_one_core'],reverse=True),'reported_cpu_clocks':clocks,'thermal':thermal,'memory':mem,'cpu_units':'100 percent process CPU is one logical core; global cpu utilization is percentage across all cores'})+'\n');file.flush()
            previous=current;previous_cpu=cpu;previous_time=now
if __name__=='__main__':main()
