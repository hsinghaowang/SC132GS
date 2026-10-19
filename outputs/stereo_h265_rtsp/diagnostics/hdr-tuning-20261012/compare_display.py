"""Compare proposed display responses on one preserved decoded Main10 frame.

These images are offline proposals, not sensor or live RTSP changes.
"""
from pathlib import Path
import json
import numpy as np
from PIL import Image, ImageDraw

root = Path(__file__).parent
source = np.fromfile(root / 'total1492-gain21-second1.u16le', dtype='<u2').reshape(1280,2176)
linear = source / 1023.0
tiles = []
for name, gamma in [('Current', 1.0), ('Shadow lift A', .65), ('Shadow lift B', .5)]:
    # 52 is the previously measured profile floor, used here as a candidate.
    proposed = linear if gamma == 1 else np.clip((source.astype(float)-52)/(1023-52),0,1)**gamma
    pixels = np.rint(proposed*255).astype('uint8')
    image = Image.fromarray(pixels)
    image.save(root / f'display-gamma-{gamma}.png')
    tile = Image.new('RGB', (1088,670), 'white')
    tile.paste(image.resize((1088,640)),(0,30))
    ImageDraw.Draw(tile).text((8,8),f'{name}: gamma={gamma}, same sensor frame',fill='black')
    tiles.append(tile)
montage = Image.new('RGB',(1088,670*len(tiles)),'white')
for i,tile in enumerate(tiles):
    montage.paste(tile,(0,670*i))
montage.save(root/'display-comparison.png')
(root/'display-proposal.json').write_text(json.dumps({
    'live_applied':False,'sensor_profile':{'total_rows':1492,'second_ticks':1,'gain_index':21},
    'source':'decoded Main10 full-range luma; not original RAW',
    'candidate_black_level':52,'gamma_candidates':[.65,.5],
    'formula':'clamp((decoded_luma10-52)/(1023-52),0,1)^gamma'},indent=2))
