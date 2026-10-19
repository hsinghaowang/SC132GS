"""Independent analytic checks for alignment and pose-convention handling."""
import numpy as np
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
spec=spec_from_file_location('evaluate',Path(__file__).with_name('evaluate-euroc.py'))
module=module_from_spec(spec); spec.loader.exec_module(module)
t=np.arange(0,10,.005)
position=np.c_[np.sin(t),np.cos(t),t*.2]
ground=np.c_[t,position,np.tile([1,0,0,0],(len(t),1))]
angle=.6; c,s=np.cos(angle),np.sin(angle)
rotation=np.array([[c,-s,0],[s,c,0],[0,0,1]])
indices=np.arange(1,len(t)-1,10)
estimate=np.c_[t[indices],position[indices]@rotation.T+np.array([2,3,4]),np.tile([np.cos(angle/2),0,0,np.sin(angle/2)],(len(indices),1))]
metrics=module.accuracy(estimate,ground)
assert metrics['ate_rmse_m']<1e-10
assert metrics['rpe_translation_rmse_m']<1e-10
assert metrics['rpe_rotation_rmse_deg']<1e-5
estimate[:,1:4]*=2
assert module.accuracy(estimate,ground)['ate_rmse_m']>.5
print('PASS: rigid alignment, no-scale policy, Hamilton body-to-world RPE')
