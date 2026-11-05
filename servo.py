"""Scasso servo accessibile dall'intradosso e battuta per un futuro coperchio."""
import math
from planform import planform_section

# Ingombri iniziali indicativi, non specifiche universali associate al peso.
# Assi nominali: X larghezza, Y altezza, Z lunghezza lungo l'apertura.
SERVO_PRESETS={1:(8.5,16.,20.),2:(11.,22.,22.),3:(12.,24.,23.)}
SERVO_DEFAULTS=dict(servo_type=1,servo_dist_root_mm=100.,servo_dist_le_mm=64.,
    servo_rotate_z_deg=-7.,servo_rotate_y_deg=45.,servo_dist_depth_mm=10.,servo_clearance_mm=.3,
    servo_lid_lip_mm=2.,servo_lid_depth_mm=.8)


def servo_parameters(params):
    if str(params.get('create_servo_void',False)).lower() not in ('1','true','on','yes'):return None
    axis=str(params.get('servo_rotation_axis','z')).lower().strip()
    if axis not in ('z','y'):raise ValueError('Scegli una sola modalità di rotazione servo: asse Z oppure in pianta (asse Y).')
    s={key:float(str(params.get(key,value)).replace(',','.')) for key,value in SERVO_DEFAULTS.items() if key not in ('servo_rotate_z_deg','servo_rotate_y_deg')}
    for key,active in (('servo_rotate_z_deg',axis=='z'),('servo_rotate_y_deg',axis=='y')):
        s[key]=float(str(params.get(key,SERVO_DEFAULTS[key])).replace(',','.')) if active else 0.
    if s['servo_type'] not in SERVO_PRESETS:raise ValueError('Tipo servo richiesto: 1=3,7 g, 2=5 g, 3=9 g.')
    s['servo_type']=int(s['servo_type']);width,height,length=SERVO_PRESETS[s['servo_type']]
    for key,value in (('servo_width_mm',width),('servo_height_mm',height),('servo_length_mm',length)):
        s[key]=float(str(params.get(key,value)).replace(',','.'))
    if not all(math.isfinite(v) for v in s.values()):raise ValueError('I parametri servo devono essere numeri finiti.')
    if min(s[k] for k in ('servo_width_mm','servo_height_mm','servo_length_mm','servo_lid_lip_mm','servo_lid_depth_mm'))<=0:
        raise ValueError('Dimensioni servo e battuta devono essere positive.')
    if s['servo_clearance_mm']<0:raise ValueError('Il gioco servo non può essere negativo.')
    if axis=='y' and abs(s['servo_rotate_y_deg'])>180:raise ValueError('Rotazione in pianta richiesta tra -180 e 180 gradi.')
    if abs(s['servo_rotate_z_deg'])>=80:raise ValueError('Rotazione servo richiesta tra -80 e 80 gradi esclusi.')
    if s['servo_dist_le_mm']<=0:raise ValueError('La distanza servo dal bordo d’attacco deve essere positiva.')
    if s['servo_lid_depth_mm']<.2:raise ValueError('Usa almeno 0,2 mm di profondità per la battuta.')
    if s['servo_lid_lip_mm']<2*float(str(params.get('larghezza_linea_vaso',.55)).replace(',','.')):
        raise ValueError('Battuta servo troppo stretta: usa almeno due larghezze linea.')
    s['servo_rotation_axis']=axis
    return s


def servo_surface(params,z,x,upper=False):
    from core import section_profile
    p=dict(params,points=max(80,params['points']))
    chord,lead,_=planform_section(p,z)
    profile=section_profile(p,z,max(.9,2*float(str(p.get('larghezza_linea_vaso',.55)).replace(',','.')))/chord)
    n=p['points'];curve=profile[:n+1] if upper else [profile[0]]+list(reversed(profile[n+1:]))
    values=[]
    for (xa,ya),(xb,yb) in zip(curve,curve[1:]):
        xa=lead+xa*chord;xb=lead+xb*chord
        if min(xa,xb)-1e-8<=x<=max(xa,xb)+1e-8 and abs(xb-xa)>1e-10:
            values.append(chord*(ya+(yb-ya)*(x-xa)/(xb-xa)))
    if not values:raise ValueError('Scasso servo fuori dal profilo: modifica distanza dal bordo d’attacco o posizione dalla radice.')
    return max(values) if upper else min(values)


def servo_layout(params):
    s=servo_parameters(params)
    if not s:return None
    z=s['servo_dist_root_mm'];x=planform_section(params,z)[1]+s['servo_dist_le_mm']
    clearance=s['servo_clearance_mm'];width=s['servo_width_mm']+2*clearance
    height=s['servo_height_mm']+2*clearance;length=s['servo_length_mm']+2*clearance
    cy=-s['servo_dist_depth_mm']+s['servo_height_mm']/2
    angle=math.radians(s['servo_rotate_z_deg']);c,si=math.cos(angle),math.sin(angle)
    body=[(x+dx*c-dy*si,cy+dx*si+dy*c) for dx in (-width/2,width/2) for dy in (-height/2,height/2)]
    inner=(min(v[0] for v in body)-clearance,max(v[0] for v in body)+clearance,z-length/2,z+length/2)
    lip=s['servo_lid_lip_mm'];outer=(inner[0]-lip,inner[1]+lip,inner[2]-lip,inner[3]+lip)
    def polygon(bounds):
        xmin,xmax,zmin,zmax=bounds
        return [(xmin,zmin),(xmax,zmin),(xmax,zmax),(xmin,zmax)]
    inner_polygon=polygon(inner);outer_polygon=polygon(outer)
    if s['servo_rotation_axis']=='y':
        angle=math.radians(s['servo_rotate_y_deg']);c,si=math.cos(angle),math.sin(angle)
        def turn(point):
            xx,zz=point;return (x+(xx-x)*c+(zz-z)*si,z-(xx-x)*si+(zz-z)*c)
        inner_polygon=[turn(v) for v in inner_polygon];outer_polygon=[turn(v) for v in outer_polygon]
        def bounds(poly):return (min(v[0] for v in poly),max(v[0] for v in poly),min(v[1] for v in poly),max(v[1] for v in poly))
        inner=bounds(inner_polygon);outer=bounds(outer_polygon)
    if not 0<outer[2]<outer[3]<params['span']:
        raise ValueError('Scasso e battuta servo devono rientrare nella semiala principale: modifica posizione dalla radice o lunghezza.')
    for zz in (outer[2],z,outer[3]):
        for xx in (outer[0],(outer[0]+outer[1])/2,outer[1]):
            bottom=servo_surface(params,zz,xx)
            if bottom+s['servo_lid_depth_mm']+.8>=servo_surface(params,zz,xx,True):
                raise ValueError('Spessore ala insufficiente per la battuta del pannello servo.')
    protrusion=max(0.,max(servo_surface(params,zz,xx)-yy for zz in (inner[2],z,inner[3]) for xx,yy in body))
    upper_margin=min(servo_surface(params,zz,xx,True)-yy for zz in (inner[2],z,inner[3]) for xx,yy in body)
    if s['servo_rotation_axis']=='y':
        samples=[(x+dx*c+dz*si,cy+dy,z-dx*si+dz*c) for dx in (-width/2,width/2) for dz in (-length/2,length/2) for dy in (-height/2,height/2)]
        protrusion=max(0.,max(servo_surface(params,zz,xx)-yy for xx,yy,zz in samples))
        upper_margin=min(servo_surface(params,zz,xx,True)-yy for xx,yy,zz in samples)
    s.update(center_x=x,center_y=cy,center_z=z,inner_bounds=inner,outer_bounds=outer,inner_polygon=inner_polygon,outer_polygon=outer_polygon,
             body_top_y=max(p[1] for p in body),body_bottom_y=min(p[1] for p in body),protrusion_under_mm=protrusion,upper_margin_mm=upper_margin)
    return s


def servo_footprint(layout,key,closed=False):
    polygon=layout[key.replace('_bounds','_polygon')]
    return polygon+[polygon[0]] if closed else polygon


def make_servo_geometry(cq,params,ligament):
    s=servo_layout(params)
    if not s:return None
    pad=3*max(params['root_chord'],params['span'],params['tip_chord'])
    x,y,z=s['center_x'],s['center_y'],s['center_z'];clearance=s['servo_clearance_mm']
    width=s['servo_width_mm']+2*clearance;length=s['servo_length_mm']+2*clearance
    top=y+s['servo_height_mm']/2+clearance
    body=cq.Workplane('XY').box(width,top+pad,length).translate((x,(top-pad)/2,z)).val()
    body=body.rotate((x,y,0),(x,y,1),s['servo_rotate_z_deg'])
    if s['servo_rotation_axis']=='y':body=body.rotate((x,y,z),(x,y+1,z),s['servo_rotate_y_deg'])
    def prism(polygon):
        wire=cq.Wire.makePolygon([cq.Vector(xx,-pad,zz) for xx,zz in polygon],close=True)
        return cq.Solid.extrudeLinear(wire,[],cq.Vector(0,2*pad,0))
    def surface_pocket(bounds,depth):
        xmin,xmax,zmin,zmax=bounds;wires=[]
        for i in range(9):
            zz=zmin+(zmax-zmin)*i/8
            surface=[(xmin+(xmax-xmin)*j/16,0.) for j in range(17)]
            pts=[cq.Vector(xx,servo_surface(params,zz,xx)+depth,zz) for xx,_ in surface]
            pts.extend((cq.Vector(xmax,-pad,zz),cq.Vector(xmin,-pad,zz)))
            wires.append(cq.Wire.makePolygon(pts,close=True))
        return cq.Solid.makeLoft(wires,ruled=True)
    lip=surface_pocket(s['outer_bounds'],s['servo_lid_depth_mm'])
    entry=surface_pocket(s['inner_bounds'],s['servo_lid_depth_mm']+2*ligament)
    if s['servo_rotation_axis']=='y':
        lip=lip.intersect(prism(s['outer_polygon']))
        entry=entry.intersect(prism(s['inner_polygon']))
    xmin,xmax,zmin,zmax=s['outer_bounds']
    guard=cq.Workplane('XY').box(xmax-xmin+2*ligament,2*pad,zmax-zmin+2*ligament).translate(((xmin+xmax)/2,0,(zmin+zmax)/2)).val()
    if s['servo_rotation_axis']=='y':
        c=math.cos(math.radians(s['servo_rotate_y_deg']));si=math.sin(math.radians(s['servo_rotate_y_deg']))
        expanded=[]
        for xx,zz in ((-width/2-clearance-s['servo_lid_lip_mm']-ligament,-length/2-s['servo_lid_lip_mm']-ligament),
                      (width/2+clearance+s['servo_lid_lip_mm']+ligament,-length/2-s['servo_lid_lip_mm']-ligament),
                      (width/2+clearance+s['servo_lid_lip_mm']+ligament,length/2+s['servo_lid_lip_mm']+ligament),
                      (-width/2-clearance-s['servo_lid_lip_mm']-ligament,length/2+s['servo_lid_lip_mm']+ligament)):
            expanded.append((x+xx*c+zz*si,z-xx*si+zz*c))
        guard=prism(expanded)
    levels=[zmin,zmin+ligament,s['inner_bounds'][2],s['inner_bounds'][3],zmax-ligament,zmax]
    levels.extend(v[1] for poly in (s['outer_polygon'],s['inner_polygon']) for v in poly)
    return dict(body=body,lip=lip,entry=entry,guard=guard,details=s,levels=sorted(set(levels)))
