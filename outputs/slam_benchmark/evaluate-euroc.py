"""SE(3) position ATE and one-second pose RPE; no scale correction."""
import json
import sys
from pathlib import Path
import numpy as np

def rotations(q):
    q = q/np.linalg.norm(q, axis=1)[:, None]
    w,x,y,z = q.T
    return np.stack([1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)], axis=1).reshape(-1,3,3)

def accuracy(est, ground):
    t = est[:,0]
    upper = np.searchsorted(ground[:,0], t)
    valid = (upper>0)&(upper<len(ground))
    upper = np.clip(upper,1,len(ground)-1)
    lower = upper-1
    span = ground[upper,0]-ground[lower,0]
    valid &= span <= .011
    est = est[valid]; upper=upper[valid]; lower=lower[valid]; span=span[valid]
    if len(est)<20: raise ValueError('insufficient ground truth overlap')
    alpha = ((est[:,0]-ground[lower,0])/span)[:,None]
    target = ground[lower,1:4]*(1-alpha)+ground[upper,1:4]*alpha
    q0, q1 = ground[lower,4:8].copy(), ground[upper,4:8].copy()
    q1[np.sum(q0*q1,axis=1)<0] *= -1
    target_rot = rotations(q0*(1-alpha)+q1*alpha)
    position = est[:,1:4]
    source_rot = rotations(est[:,4:8])
    source_mean, target_mean = position.mean(axis=0), target.mean(axis=0)
    u,_,vt = np.linalg.svd((position-source_mean).T@(target-target_mean))
    fix = np.eye(3); fix[2,2]=np.linalg.det(vt.T@u.T)
    alignment=vt.T@fix@u.T
    errors=np.linalg.norm((alignment@(position-source_mean).T).T+target_mean-target,axis=1)
    desired=est[:,0]+1
    j=np.searchsorted(est[:,0],desired)
    good=j<len(est); i=np.arange(len(est))[good]; j=j[good]
    previous=np.maximum(j-1,0)
    choose_previous=np.abs(est[previous,0]-desired[i])<np.abs(est[j,0]-desired[i])
    j=np.where(choose_previous,previous,j)
    good=np.abs(est[j,0]-est[i,0]-1)<=.026; i=i[good]; j=j[good]
    source_delta=np.einsum('nji,nj->ni',source_rot[i],position[j]-position[i])
    target_delta=np.einsum('nji,nj->ni',target_rot[i],target[j]-target[i])
    translation=np.linalg.norm(source_delta-target_delta,axis=1)
    source_relative=np.swapaxes(source_rot[i],1,2)@source_rot[j]
    target_relative=np.swapaxes(target_rot[i],1,2)@target_rot[j]
    error_rot=np.swapaxes(target_relative,1,2)@source_relative
    angles=np.rad2deg(np.arccos(np.clip((np.trace(error_rot,axis1=1,axis2=2)-1)/2,-1,1)))
    return {'ate_rmse_m':float(np.sqrt(np.mean(errors**2))), 'ate_alignment':'full-trajectory rigid SE3, scale fixed to 1', 'rpe_interval_s':1, 'rpe_pairs':len(i), 'rpe_translation_rmse_m':float(np.sqrt(np.mean(translation**2))), 'rpe_rotation_rmse_deg':float(np.sqrt(np.mean(angles**2))), 'ground_truth_matched_poses':len(est), 'ground_truth_match_policy':'linear position and normalized shortest-arc quaternion interpolation; maximum bracket 11 ms', 'matched_start_timestamp':float(est[0,0]), 'matched_end_timestamp':float(est[-1,0])}

def stats(values):
    values=np.asarray(values); values=values[np.isfinite(values)]
    return {key:float(value) for key,value in zip(('p50','p95','p99','max'),np.r_[np.percentile(values,[50,95,99]),values.max()])} if len(values) else None

def main():
    base,gt_path=map(Path,sys.argv[1:3])
    dataset=sys.argv[3] if len(sys.argv)>3 else 'MH_01_easy'
    gt=np.loadtxt(gt_path,delimiter=',',comments='#');gt[:,0]*=1e-9
    results=[]
    for output in sorted(base.glob(dataset+'-*')):
        if not (output/'summary.json').exists(): continue
        summary=json.loads((output/'summary.json').read_text())
        summary['dataset']=dataset
        frames=np.genfromtxt(output/'frames.csv',delimiter=',',names=True)
        trajectory=np.loadtxt(output/'trajectory.csv',delimiter=',',comments='#',ndmin=2)
        summary.update(accuracy(trajectory,gt))
        summary['run']=output.name
        summary['pose_frame_coverage']=summary['poses']/summary['frames']
        initialized=frames['initialized']==1
        summary['initialization_delay_dataset_s']=float(frames['camera_timestamp'][initialized][0]-frames['camera_timestamp'][0])
        summary['post_initialization_pose_frame_coverage']=summary['poses']/int(np.sum(initialized))
        summary['initialized_processing_pair_rate_hz']=float(np.sum(initialized)*1000/np.sum(frames['read_ms'][initialized]+frames['imu_ms'][initialized]+frames['estimator_ms'][initialized]))
        summary['all_frame_processing_ms']=stats(frames['estimator_ms'])
        summary['initialized_frame_processing_ms']=stats(frames['estimator_ms'][frames['initialized']==1])
        summary['image_read_ms']=stats(frames['read_ms'])
        internal=np.loadtxt(output/'internal-timing.csv',delimiter=',',comments='#',ndmin=2)
        summary['frontend_tracking_ms']=stats(internal[:,1]*1000)
        summary['internal_total_ms']=stats(internal[:,-1]*1000)
        summary['playback_completion_lag_ms']=stats(frames['completion_lag_ms'])
        summary['input_pairs_per_wall_second']=summary['frames']/summary['elapsed_s']
        summary['pose_updates_per_wall_second']=summary['poses']/summary['elapsed_s']
        summary['initialized_nonadvancing_frames']=int(np.sum((frames['initialized']==1)&(frames['state_advanced']==0)))
        summary['over_50ms_initialized_frames']=int(np.sum((frames['initialized']==1)&(frames['estimator_ms']>50)))
        summary['initialized_read_plus_estimate_ms']=stats(frames['read_ms'][initialized]+frames['imu_ms'][initialized]+frames['estimator_ms'][initialized])
        if summary['paced']:
            summary['playback_lag_first_100_median_ms']=float(np.median(frames['completion_lag_ms'][initialized][:100]))
            summary['playback_lag_last_100_median_ms']=float(np.median(frames['completion_lag_ms'][initialized][-100:]))
        summary['resources']=json.loads((output/'resources.json').read_text())
        (output/'evaluation.json').write_text(json.dumps(summary,indent=2))
        results.append(summary)
    all_results=[json.loads(p.read_text()) for p in sorted(base.glob('*/evaluation.json'))]
    (base/'evaluation.json').write_text(json.dumps({'platform':'RUBIK Pi 3 QCS6490', 'scope':'native sequential image/IMU replay; ROS DDS and physical sensors excluded', 'runs':all_results},indent=2))
    print(json.dumps(results,indent=2))

if __name__=='__main__': main()
