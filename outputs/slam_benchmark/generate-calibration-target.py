import json
from pathlib import Path
from PIL import Image,ImageDraw
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib.units import mm

base=Path(__file__).resolve().parent
output=base.parents[1]/'output/pdf';output.mkdir(parents=True,exist_ok=True)
pdf=output/'sc132gs-checkerboard-a4-20mm.pdf'
width,height=landscape(A4)
x,y=48.5*mm,35*mm
page=canvas.Canvas(str(pdf),pagesize=(width,height))
page.setTitle('SC132GS stereo calibration - 9x6 inner corners, 20 mm squares')
page.setFont('Helvetica-Bold',11)
page.drawCentredString(width/2,198*mm,'SC132GS STEREO - 9 x 6 INNER CORNERS - 20 mm SQUARES')
for row in range(7):
    for col in range(10):
        if (row+col)%2==0:
            page.rect(x+col*20*mm,y+row*20*mm,20*mm,20*mm,stroke=0,fill=1)
page.setLineWidth(.6)
page.line(x,12*mm,x+50*mm,12*mm)
page.line(x,10*mm,x,14*mm);page.line(x+50*mm,10*mm,x+50*mm,14*mm)
page.setFont('Helvetica',8)
page.drawString(x+55*mm,11*mm,'Measure this line: 50 mm. Print Actual Size / 100%, then remeasure squares.')
page.drawCentredString(width/2,5*mm,'Landscape A4. Mount flat on a rigid board. Entire pattern must be visible in BOTH cameras.')
page.showPage();page.save()
reader=PdfReader(pdf)
assert len(reader.pages)==1
assert abs(float(reader.pages[0].mediabox.width)-width)<.01
assert abs(float(reader.pages[0].mediabox.height)-height)<.01
target=base/'calibration-capture/checkerboard.yaml'
target.write_text('target_type: checkerboard\ntargetCols: 9\ntargetRows: 6\nrowSpacingMeters: 0.020\ncolSpacingMeters: 0.020\n',encoding='utf-8')
# Independently generated ideal pattern for OpenCV detector verification.
image=Image.new('L',(1320,1040),255);draw=ImageDraw.Draw(image)
for row in range(7):
    for col in range(10):
        if (row+col)%2==0:draw.rectangle((160+col*100,170+row*100,160+(col+1)*100-1,170+(row+1)*100-1),fill=0)
image.save(base/'calibration-capture/checkerboard-detector-test.png')
(base/'calibration-capture/target-dimensions.json').write_text(json.dumps(dict(page_mm=[297,210],
    squares=[10,7],internal_corners=[9,6],square_mm=20,pattern_mm=[200,140],ruler_mm=50,
    print_scale_must_be_measured=True,reference='https://github.com/ethz-asl/kalibr/wiki/calibration-targets'),indent=2))
print(pdf)
