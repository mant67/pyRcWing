"""Shared nominal planform; all lengths in mm, span along Z."""
import math

def elliptical_planform(p):
    return str(p.get('planform','trapezoidal')) == 'elliptical'

def planform_parameters(p):
    mode=str(p.get('planform','trapezoidal'))
    if mode not in ('trapezoidal','elliptical'):raise ValueError('Scegli una pianta trapezoidale o ellittica.')
    if not elliptical_planform(p):return dict(planform=mode)
    q=float(str(p.get('ellipse_center_perc',50)).replace(',','.'))
    cr,ct=float(p['root_chord']),float(p['tip_chord'])
    if not math.isfinite(q) or not 0<=q<=100:raise ValueError('Linea centrale ellisse richiesta tra 0 e 100%.')
    if not 0<ct<cr:raise ValueError('Pianta ellittica: la corda terminale deve essere positiva e minore della corda radice.')
    # Finite terminal profile avoids a degenerate slit at a mathematical point.
    thickness=int(str(p.get('airfoil_tip',p.get('airfoil','2412')))[2:])/100
    width=float(str(p.get('larghezza_linea_vaso',.55)).replace(',','.'))
    if ct*thickness<4*width:raise ValueError('Pianta ellittica: aumenta la corda terminale (spessore NACA minimo: quattro larghezze linea).')
    return dict(planform=mode,ellipse_center_perc=q)

def planform_section(p,z):
    f=z/p['span'];cr,ct=p['root_chord'],p['tip_chord']
    if not elliptical_planform(p):return cr+(ct-cr)*f,p['sweep']*f,1.
    f=max(0.,min(1.,f))
    q=float(str(p.get('ellipse_center_perc',50)).replace(',','.'))/100
    chord=math.sqrt(max(ct*ct,cr*cr-(cr*cr-ct*ct)*f*f))
    return chord,p['sweep']*f+(cr-chord)*q,1.

def planform_stations(p):
    n=int(p['stations'])
    if not elliptical_planform(p):return [p['span']*i/n for i in range(n+1)]
    # Angular sampling refines the rapidly turning terminal region.
    n=max(24,n);end=math.acos(p['tip_chord']/p['root_chord'])
    return [p['span']*math.sin(end*i/n)/math.sin(end) for i in range(n+1)]

def planform_outline(p,n=80):
    sections=[(p['span']*i/n,planform_section(p,p['span']*i/n)) for i in range(n+1)]
    return [(z,lead) for z,(ch,lead,_) in sections]+[(z,lead+ch) for z,(ch,lead,_) in reversed(sections)]


def planform_rib_segments(p):
    """Schematic X/Z traces using the same planes and Z reflection as the CAD."""
    if str(p.get('create_ribs',True)).lower() not in ('1','true','yes','on'):return
    pitch=float(str(p.get('rib_pitch',40)).replace(',','.'))
    angle=float(str(p.get('rib_angle',45)).replace(',','.'))
    if not math.isfinite(pitch) or pitch<=0 or not 20<=angle<=70:return
    mirrored=str(p.get('nervature_specchiate_ala',False)).lower() in ('1','true','yes','on')
    total=p['span']
    if str(p.get('elliptical_tip',False)).lower() in ('1','true','yes','on'):
        total+=float(str(p.get('tip_length',40)).replace(',','.'))
    if not math.isfinite(total) or total<=0:return
    slope=math.tan(math.radians(angle))
    if (total+max(p['root_chord'],p['tip_chord'])*slope)/pitch>2000:return
    poly=planform_outline(p);d=1+slope*p['sweep']/p['span']
    base=-max(p['root_chord'],p['tip_chord'])*slope
    while base<=total+1e-7:
        for family in ('original','mirrored') if mirrored else ('original',):
            a=(0.,(base if family=='mirrored' else -base)/slope)
            if family=='mirrored':a=(0.,(d*total-base)/slope)
            b=(p['span'],(d*p['span']-base)/slope if family=='original' else (d*(total-p['span'])-base)/slope)
            delta=(b[0]-a[0],b[1]-a[1]);lo,hi=0.,1.
            for v,w in zip(poly,poly[1:]+poly[:1]):
                ez,ex=w[0]-v[0],w[1]-v[1]
                initial=ez*(a[1]-v[1])-ex*(a[0]-v[0]);rate=ez*delta[1]-ex*delta[0]
                if abs(rate)<1e-12:
                    if initial < -1e-8:hi=-1.;break
                elif rate>0:lo=max(lo,-initial/rate)
                else:hi=min(hi,-initial/rate)
                if lo>=hi:break
            if hi-lo>1e-7:
                yield family,[(a[0]+t*delta[0],a[1]+t*delta[1]) for t in (lo,hi)]
        base+=pitch
