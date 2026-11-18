from pathlib import Path
import csv,re,json,sys
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import HexColor,Color,white
from reportlab.lib.utils import simpleSplit

GROUPS=[
    [('Passenger vehicles', [('accel_high','High acceleration'),('accel_low','Low acceleration'),('decel_high','High deceleration'),('decel_low','Low deceleration'),('mingap_high','Large minimum gap'),('mingap_low','Small minimum gap'),('speed_high','High maximum speed'),('speed_low','Low maximum speed')]),
     ('Headway and randomness',[('reaction_fast','Short desired headway'),('reaction_slow','Long desired headway'),('sigma_high','High randomness'),('sigma_low','Low randomness')])],
    [('Demand volume',[('demand_low','Low demand'),('demand_high','High demand'),('demand_peak','Peak demand')]),
     ('Composition and weather',[('heavyveh_mid','Heavy vehicles: 8%'),('heavyveh_high','Heavy vehicles: 16%'),('heavyveh_very_high','Heavy vehicles: 24%'),('weather_rain','Rain'),('weather_heavy_rain','Heavy rain')]),
     ('Signals and bottlenecks',[('signal_green_short','Short-phase variant'),('signal_green_long','Long-phase variant'),('signal_losttime_high','Yellow extension'),('signal_offset_mismatch','Offset variant'),('lane_control_ed2','Lane restriction'),('bottleneck_speed_drop','Local speed restriction')])]]
def generate(project):
    src=project/'reproducibility/pointwise_intervals.csv'
    with src.open(encoding='utf-8-sig',newline='') as f:
        data={d['scenario']:d for d in csv.DictReader(f) if d['response']=='throughput'}
    assert {i for col in GROUPS for _,rs in col for i,_ in rs}==set(data) and len(data)==26
    width,height=552,301
    c=Canvas(str(project/'figures/Fig_oat_paired_intervals.pdf'),pagesize=(width,height),invariant=1)
    c.setTitle('Route-completion throughput: three-seed paired responses')
    c.setAuthor('')
    ink='#202B32';muted='#4B5962';grid='#DCE2E4';primary='#176174';alert='#9E451A'
    def text(x,y,s,size=8,color=ink,bold=False,align='left'):
        c.setFillColor(HexColor(color));c.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
        {'left':c.drawString,'center':c.drawCentredString,'right':c.drawRightString}[align](x,y,s)
    def segment(x,y,X,Y,color,lw):
        c.setLineWidth(lw);c.setStrokeColor(HexColor(color));c.line(x,y,X,Y)
    def marker(x,y,warn):
        cc=HexColor(alert if warn else primary);c.setStrokeColor(cc);c.setLineWidth(1.05)
        if warn:
            c.setFillColor(white); p=c.beginPath();p.moveTo(x,y+2.9);p.lineTo(x+2.9,y);p.lineTo(x,y-2.9);p.lineTo(x-2.9,y);p.close();c.drawPath(p,stroke=1,fill=1)
        else:c.setFillColor(cc);c.circle(x,y,2.45,fill=1,stroke=0)
    for col,groups in enumerate(GROUPS):
        x0=[3,283][col];L=x0+105;R=x0+256
        X=lambda z:L+(z+25)*(R-L)/45
        text(x0,286,['a   Vehicle behavior','b   Demand, fleet and network'][col],10,bold=True)
        for tick in [-20,-10,0,10,20]:
            segment(X(tick),46,X(tick),270,('#53616A' if tick==0 else grid),(.75 if tick==0 else .40))
            text(X(tick),32,(('+' if tick>0 else '')+str(tick)),7.8,muted,align='center')
        y=267
        for name,rows in groups:
            text(x0,y,name,8,muted,True);y-=12
            for ident,label in rows:
                v=data[ident];assert v['n']=='3'
                mean,lo,hi=[float(v[k]) for k in ('mean','ci95_low','ci95_high')]
                q=v['warning_qualified'].lower()=='true';colour=alert if q else primary
                assert -25<=lo<=mean<=hi<=20
                text(x0,y-2.5,label,8.2)
                segment(X(lo),y,X(hi),y,colour,.94)
                for z in [lo,hi]:segment(X(z),y-1.8,X(z),y+1.8,colour,.84)
                marker(X(mean),y,q)
                y-=12.05
            y-=2.1
        assert y>40
    text(276,17.0,'Change in throughput relative to the matched baseline (%)',8.8,ink,align='center')
    marker(114,5.7,False);text(121,3,'No core warning recorded',7.7,muted)
    marker(287,5.7,True);text(294,3,'Core warning in at least one paired run',7.7,muted)
    c.showPage();c.save()
if __name__=='__main__':generate(Path(__file__).resolve().parents[1])

