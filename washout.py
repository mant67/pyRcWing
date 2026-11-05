"""Washout progressivo delle sezioni e delle mesh STL, con Z invariata."""
from planform import planform_section, elliptical_planform
import bisect
import math
import struct


def washout_parameters(params):
    span=float(params['span'])
    defaults={'washout_deg':0.,'washout_start':min(60.,span),'washout_pivot_perc':25.}
    result={key:float(str(params.get(key,value)).replace(',','.')) for key,value in defaults.items()}
    if not all(math.isfinite(v) for v in result.values()):
        raise ValueError('I parametri washout devono essere numeri finiti.')
    if not 0<=result['washout_pivot_perc']<=100:
        raise ValueError('Perno washout richiesto tra 0 e 100% della corda.')
    if result['washout_start']<0:
        raise ValueError('L’inizio washout non può precedere la radice.')
    if result['washout_deg'] and result['washout_start']>=span:
        raise ValueError('Con washout attivo, l’inizio deve precedere l’estremità della semiala.')
    if abs(result['washout_deg'])>90:
        raise ValueError('Angolo washout richiesto tra -90 e 90 gradi.')
    return result


def washout_angle(params,z):
    w=washout_parameters(params)
    if not w['washout_deg']:return 0.
    t=max(0.,min(1.,(z-w['washout_start'])/(params['span']-w['washout_start'])))
    return w['washout_deg']*t


def washout_point(params,point,z_offset=0.):
    x,y,z=point;world_z=z+z_offset
    angle=math.radians(washout_angle(params,world_z))
    if angle==0:return tuple(point)
    t=max(0.,min(1.,world_z/params['span']))
    chord,lead,_=planform_section(params,t*params['span'])
    pivot=lead+chord*washout_parameters(params)['washout_pivot_perc']/100
    c,s=math.cos(angle),math.sin(angle)
    return (pivot+(x-pivot)*c-y*s,(x-pivot)*s+y*c,z)


def washout_mesh(params,points,triangles,z_offset=0.,tolerance=.005,progress=None):
    """Taglia sui livelli comuni prima di ruotare, preservando spigoli condivisi.

    La suddivisione limita l'errore delle facce fra due sezioni ruotate;
    include sempre l'inizio del washout e la fine della semiala.
    """
    w=washout_parameters(params)
    if not w['washout_deg']:return points,triangles
    span=params['span'];start=w['washout_start'];length=span-start
    rate=abs(math.radians(w['washout_deg'])/length)
    radius=2*max(params['root_chord'],params['tip_chord'])
    pivot_slope=abs((params['sweep']+(params['tip_chord']-params['root_chord'])*w['washout_pivot_perc']/100)/span)
    if elliptical_planform(params):
        q=w['washout_pivot_perc']/100;center=float(str(params.get('ellipse_center_perc',50)).replace(',','.'))/100
        chord_slope=(params['root_chord']**2-params['tip_chord']**2)/(span*params['tip_chord'])
        pivot_slope=abs(params['sweep']/span)+abs(q-center)*chord_slope
    curvature=radius*rate*rate+2*pivot_slope*rate
    step=min(10.,math.sqrt(8*max(1e-7,tolerance/2)/max(curvature,1e-12)))
    count=max(1,math.ceil(length/step))
    if count>20000:raise ValueError('Washout troppo concentrato: aumenta la distanza dall’estremità.')
    levels=[start+length*i/count-z_offset for i in range(count+1)]
    # Cut planes must use the same float32 grid as the source STL. Otherwise
    # a plane a few millionths from an existing vertex creates sliver fans
    # which collapse onto that vertex when the rotated STL is quantized.
    vertex_z=sorted(set(p[2] for p in points))
    snapped=[]
    for z in levels:
        at=bisect.bisect_left(vertex_z,z)
        nearby=vertex_z[max(0,at-1):at+1]
        ulp=2.**(math.frexp(max(1.,abs(z)))[1]-24)
        closest=min(nearby,key=lambda value:abs(value-z)) if nearby else z
        snapped.append(closest if abs(closest-z)<=2*ulp else z)
    levels=sorted(set(snapped))
    refined=list(points);cache={};result=[]
    def crossing(a,b,index):
        za,zb=refined[a][2],refined[b][2];z=levels[index]
        if abs(za-z)<1e-7:return a
        if abs(zb-z)<1e-7:return b
        key=(min(a,b),max(a,b),index)
        if key not in cache:
            # Ordine unico per evitare arrotondamenti diversi sui due lati.
            a,b=key[:2];pa,pb=refined[a],refined[b];t=(z-pa[2])/(pb[2]-pa[2])
            cache[key]=len(refined)
            refined.append((pa[0]+(pb[0]-pa[0])*t,pa[1]+(pb[1]-pa[1])*t,z))
        return cache[key]
    for ti,triangle in enumerate(triangles):
        if progress and ti%max(1,len(triangles)//100)==0:progress('washout',ti,len(triangles))
        polygons=[list(triangle)]
        low=min(refined[v][2] for v in triangle);high=max(refined[v][2] for v in triangle)
        for index in range(bisect.bisect_right(levels,low+1e-7),bisect.bisect_left(levels,high-1e-7)):
            z=levels[index];next_polygons=[]
            for polygon in polygons:
                if min(refined[v][2] for v in polygon)>=z-1e-7 or max(refined[v][2] for v in polygon)<=z+1e-7:
                    next_polygons.append(polygon);continue
                halves=[[],[]]
                for a,b in zip(polygon,polygon[1:]+polygon[:1]):
                    za,zb=refined[a][2],refined[b][2]
                    if za<=z+1e-7:halves[0].append(a)
                    if za>=z-1e-7:halves[1].append(a)
                    if (za<z-1e-7 and zb>z+1e-7) or (za>z+1e-7 and zb<z-1e-7):
                        v=crossing(a,b,index);halves[0].append(v);halves[1].append(v)
                next_polygons.extend(h for h in halves if len(h)>=3)
            polygons=next_polygons
        for polygon in polygons:
            result.extend([polygon[0],polygon[j],polygon[j+1]] for j in range(1,len(polygon)-1))
    # Le coordinate finali sono quelle che saranno scritte nello STL float32.
    warped=[struct.unpack('<3f',struct.pack('<3f',*washout_point(params,p,z_offset))) for p in refined]
    if progress:progress('washout',len(triangles),len(triangles))
    return warped,result
