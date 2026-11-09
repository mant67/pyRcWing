"""Parametric section couplers for the single-contour Spiral Vase representation.

The receiving region is an unbranched nominal envelope: its printed interior,
not an inner CAD wire, is the socket. Never introduce a closed inner ring.
"""
# File revision: 2
import copy
import math

JOINER_DEFAULTS=dict(JoinerEnabled='0',JoinerLength='8',JoinerClearance='0.1',
    JoinerLeadInOffset='0.1',NozzleWidth='0.4',FemaleSupportEnabled='0',FemaleSupportGap='0.2',FemaleRibMargin='0.55')


def enabled(value):return str(value).lower() in ('1','true','yes')


def joiner_parameters(values):
    p={k:str(values.get(k,v)) for k,v in JOINER_DEFAULTS.items()}
    for key in ('JoinerEnabled','FemaleSupportEnabled'):
        if p[key] not in ('0','1'):raise ValueError('Opzione giunzioni non valida: '+key)
    if not enabled(p['JoinerEnabled']):return None
    # Legacy NozzleWidth is kept only for configuration compatibility.
    # Geometry always follows the global extrusion width, including reductions.
    p['NozzleWidth']=str(values.get('larghezza_linea_vaso','0.55'))
    result={k:enabled(p[k]) for k in ('JoinerEnabled','FemaleSupportEnabled')}
    for key in JOINER_DEFAULTS:
        if key in result:continue
        try:n=float(p[key].replace(',','.'))
        except ValueError as exc:raise ValueError('Quota giunzioni non valida: '+key) from exc
        if not math.isfinite(n) or n<0:raise ValueError('Quota giunzioni positiva e finita richiesta: '+key)
        result[key]=n
    try:nozzle=float(str(values.get('diametro_ugello','0.4')).replace(',','.'))
    except (TypeError,ValueError) as exc:raise ValueError('Diametro ugello globale non valido.') from exc
    if not math.isfinite(nozzle) or nozzle<=0 or result['NozzleWidth']<=0:
        raise ValueError('Diametro ugello e larghezza linea globali devono essere positivi e finiti.')
    if result['JoinerLength']<2*nozzle:
        raise ValueError('Lunghezza linguetta almeno doppia del diametro ugello globale.')
    if result['FemaleSupportEnabled'] and not 0<result['FemaleSupportGap']<=nozzle:
        raise ValueError('Gap supporto richiesto maggiore di 0 e non superiore al diametro ugello globale.')
    result['PrintWidth']=result['NozzleWidth']
    result['ShrinkOffset']=result['PrintWidth']+result['JoinerLeadInOffset']
    # Positive clearance EXPANDS the male; an additional inward offset would shrink the socket.
    result['FemaleInwardOffset']=result['ShrinkOffset']-result['JoinerClearance']
    if result['FemaleInwardOffset']<=0:raise ValueError('Il gioco supera la riduzione del maschio: aumenta l’invito o riduci il gioco.')
    return result


def require_joiner_dependencies():
    try:
        from shapely.geometry import Polygon
        Polygon([(0,0),(1,0),(0,1)]).buffer(.01)
    except ImportError as exc:
        import sys
        from pathlib import Path
        requirements=Path(__file__).resolve().with_name('requirements_giunzioni_v91.txt')
        raise ValueError('Shapely non disponibile nel Python usato per avviare l’applicazione. '
            'Avvia con Avvia_Wing_v91.cmd dalla cartella del progetto. '
            f'Per installare in questo ambiente: "{sys.executable}" -m pip install -r "{requirements}"') from exc


def validate_joiner_layout(cuts,height,settings,line_width):
    if not settings:return
    require_joiner_dependencies()
    if not cuts:raise ValueError('Le giunzioni richiedono almeno un taglio.')
    width=max(settings['NozzleWidth'],line_width);safety=max(width,settings['FemaleRibMargin'])
    if settings['ShrinkOffset']<width+settings['JoinerClearance']-1e-7:
        raise ValueError(f"Aumenta JoinerLeadInOffset almeno a {settings['JoinerClearance']:.3f} mm per mantenere gioco e larghezza di stampa.")
    for i,(start,end) in enumerate(zip(cuts,list(cuts[1:])+[height])):
        if end-start<=settings['JoinerLength']+safety+width:
            raise ValueError(f'Pezzo {i+2} troppo corto per la femmina: aumenta la distanza dal taglio successivo o riduci JoinerLength.')


def wire_points(wire,tolerance=.002):
    import cadquery as cq
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.TopoDS import TopoDS
    from OCP.TopAbs import TopAbs_REVERSED
    exp=BRepTools_WireExplorer(wire.wrapped);points=[]
    while exp.More():
        raw=exp.Current();edge=cq.Edge(TopoDS.Edge_s(raw));samples,_=edge.sample(tolerance)
        if raw.Orientation()==TopAbs_REVERSED:samples=list(reversed(samples))
        for v in samples:
            xy=(v.x,v.y)
            if not points or math.dist(points[-1],xy)>1e-7:points.append(xy)
        exp.Next()
    if len(points)>1 and math.dist(points[0],points[-1])<1e-7:points.pop()
    if len(points)<3:raise ValueError('Profilo di giunzione degenere.')
    return points


def polygon_wire(points,z=0):
    import cadquery as cq
    return cq.Wire.makePolygon([cq.Vector(x,y,z) for x,y in points],close=True)


def section_wire(solid,z):
    import cadquery as cq
    wires=cq.Workplane('XY').add(solid).section(z).val().Wires()
    if len(wires)!=1:raise ValueError(f'Giunzione a Z={z:.3f}: sezione con {len(wires)} contorni. Sposta il taglio fuori da sedi, asole o transizioni.')
    return wires[0].translate((0,0,-z))


def offset_face(face,distance):
    result=face.buffer(distance,join_style=1,quad_segs=12)
    if result.geom_type!='Polygon' or result.is_empty or not result.is_valid or result.interiors or result.area<1e-6:
        raise ValueError('Offset del profilo collassato o diviso: riduci invito/gioco o sposta il taglio verso una sezione più spessa.')
    return result


def rigid_xy(params,point,z,inverse=False):
    from core import washout_point,washout_parameters,planform_section
    from washout import washout_angle
    if params.get('_componente_esportazione')=='raccordo':return point
    x,y=point
    if not inverse:return washout_point(params,(x,y,z))[:2]
    angle=-math.radians(washout_angle(params,z));ch,lead,_=planform_section(params,min(params['span'],max(0,z)))
    pivot=lead+ch*washout_parameters(params)['washout_pivot_perc']/100
    return pivot+(x-pivot)*math.cos(angle)-y*math.sin(angle),(x-pivot)*math.sin(angle)+y*math.cos(angle)


def world_face(params,wire,z):
    from shapely.geometry import Polygon
    face=Polygon([rigid_xy(params,point,z) for point in wire_points(wire)])
    if not face.is_valid or face.interiors:raise ValueError('Contorno nominale non valido per la giunzione.')
    return face


def ray_radius(poly,center,direction):
    cx,cy=center;dx,dy=direction;hits=[]
    for (ax,ay),(bx,by) in zip(poly,poly[1:]+poly[:1]):
        ex,ey=bx-ax,by-ay;den=dx*ey-dy*ex
        if abs(den)<1e-12:continue
        qx,qy=ax-cx,ay-cy
        t=(qx*ey-qy*ex)/den;u=(qx*dy-qy*dx)/den
        if t>1e-8 and -1e-8<=u<=1+1e-8:hits.append(t)
    hits=sorted(hits);unique=[]
    for t in hits:
        if not unique or abs(t-unique[-1])>1e-5:unique.append(t)
    if len(unique)!=1:raise ValueError('Profilo non stellato o nervatura esterna al profilo ridotto: sposta il taglio o riduci la riduzione della linguetta.')
    return unique[0]


def mapped_pattern(pattern,source,target,center):
    result=[]
    for x,y in pattern:
        dx,dy=x-center[0],y-center[1];radius=math.hypot(dx,dy)
        if radius<1e-8:result.append(center);continue
        direction=dx/radius,dy/radius
        ratio=ray_radius(target,center,direction)/ray_radius(source,center,direction)
        result.append((center[0]+dx*ratio,center[1]+dy*ratio))
    return result


def z_box(solid,start,end):
    import cadquery as cq
    b=solid.BoundingBox();pad=max(b.xlen,b.ylen,1)+5
    return cq.Workplane('XY').box(b.xlen+2*pad,b.ylen+2*pad,end-start).translate(((b.xmin+b.xmax)/2,(b.ymin+b.ymax)/2,(start+end)/2)).val()


def valid(solid,label):
    if not solid.isValid():solid=solid.fix()
    if not solid.isValid() or len(solid.Solids())!=1 or solid.Volume()<1e-8:
        raise ValueError(label+': geometria disconnessa o non valida. Sposta il taglio o riduci la lunghezza/riduzione della linguetta.')
    return solid


def feature_conflicts(solid,cut,finish):
    """Only removed material of this component can obstruct its coupling.

    Cutter prisms may extend into the other component or outside the foil;
    testing their bounding boxes alone would cause false-positive blocks.
    """
    envelope=solid._joiner_envelope;zone=z_box(envelope,cut-1e-5,finish)
    labels=getattr(solid,'_joiner_feature_labels',[]);conflicts=[];eb=envelope.BoundingBox()
    for i,feature in enumerate(solid._joiner_features):
        bb=feature.BoundingBox()
        if bb.zmax<=cut or bb.zmin>=finish or bb.xmax<=eb.xmin or bb.xmin>=eb.xmax or bb.ymax<=eb.ymin or bb.ymin>=eb.ymax:continue
        local=feature.intersect(zone)
        if not local.Solids():continue
        actual=local.intersect(envelope)
        if not actual.Solids():continue
        if actual.Volume(tol=1e-8)>1e-7:
            conflicts.append(dict(label=labels[i] if i<len(labels) else 'Scasso servo o asola cerniera',
                start=bb.zmin,end=bb.zmax,volume=actual.Volume(tol=1e-8)))
    return sorted(conflicts,key=lambda v:v['start'])


def check_feature_conflicts(solid,cut,finish,anchor_start=None):
    start=cut if anchor_start is None else anchor_start
    conflicts=feature_conflicts(solid,start,finish)
    if not conflicts:return
    details='; '.join(f"{c['label']} (Z={c['start']:.3f}–{c['end']:.3f} mm)" for c in conflicts)
    raise ValueError(f'Taglio Z={cut:.3f} mm: la zona di innesto, compresi ancoraggio e margine, occupa Z={start:.3f}–{finish:.3f} mm. '
        f'Interferenza con: {details}. Sposta il taglio o l’elemento indicato per liberare tutta la zona, non solo il piano di taglio.')


def fitted_profile_wire(points,z,tolerance=.004):
    """Few analytic/spline edges, with a measured error bound against the offset polygon."""
    import cadquery as cq
    from shapely.geometry import Polygon,LineString,Point
    n=len(points);corners=[]
    for i in range(n):
        a=points[i-1];b=points[i];c=points[(i+1)%n]
        u=(b[0]-a[0],b[1]-a[1]);v=(c[0]-b[0],c[1]-b[1]);length=math.hypot(*u)*math.hypot(*v)
        if length>1e-14 and (u[0]*v[0]+u[1]*v[1])/length<math.cos(math.radians(45)):corners.append(i)
    if not corners:corners=[min(range(n),key=lambda i:points[i][0]),max(range(n),key=lambda i:points[i][0])]
    elif len(corners)==1:
        start=corners[0];corners.append(max(range(n),key=lambda i:math.dist(points[i],points[start])))
    corners=sorted(set(corners))
    xmax=max(points[i][0] for i in corners);first=min((i for i in corners if points[i][0]>=xmax-.02),key=lambda i:points[i][1])
    pivot=corners.index(first);corners=corners[pivot:]+[i+n for i in corners[:pivot]]
    edges=[]
    try:
        for start,end in zip(corners,corners[1:]+[corners[0]+n]):
            chunk=[points[i%n] for i in range(start,end+1)];clean=[chunk[0]]
            for point in chunk[1:-1]:
                if math.dist(clean[-1],point)>.002:clean.append(point)
            if math.dist(clean[-1],chunk[-1])>1e-8:clean.append(chunk[-1])
            if len(clean)>3:clean=list(LineString(clean).simplify(.001,preserve_topology=True).coords)
            line=LineString([clean[0],clean[-1]])
            if max(line.distance(Point(p)) for p in clean)<.0003:
                edges.append(cq.Edge.makeLine(cq.Vector(*clean[0],z),cq.Vector(*clean[-1],z)))
            else:edges.append(cq.Edge.makeSpline([cq.Vector(x,y,z) for x,y in clean],tol=1e-8))
        wire=cq.Wire.assembleEdges(edges)
        if not wire.isValid() or not wire.IsClosed():
            fitted_profile_wire.last_issue='wire non chiuso';return None
        reference=Polygon(points);actual=Polygon(wire_points(wire,.0008))
        if not actual.is_valid or actual.boundary.hausdorff_distance(reference.boundary)>tolerance:
            fitted_profile_wire.last_issue=('scarto',actual.boundary.hausdorff_distance(reference.boundary));return None
        return wire
    except (ValueError,RuntimeError) as exc:
        fitted_profile_wire.last_issue=str(exc);return None


def coherent_wires(polygons,zs,params,origin):
    """Match outlines on a fixed polar grid, including every end-profile corner."""
    from shapely.geometry.polygon import orient
    fitted=[]
    for poly,z in zip(polygons,zs):
        points=[rigid_xy(params,p,z+origin,inverse=True) for p in list(orient(poly,sign=1).exterior.coords)[:-1]]
        fitted.append(fitted_profile_wire(points,z))
    if all(w is not None for w in fitted) and len({len(w.Edges()) for w in fitted})==1:return fitted
    center=polygons[-1].representative_point();center=(center.x,center.y)
    angles=sorted(set(round(math.atan2(y-center[1],x-center[0]),8) for poly in (polygons[0],polygons[-1]) for x,y in list(poly.exterior.coords)[:-1]))
    # Add only corners whose omission would change the local normal offset.
    from shapely.geometry import Polygon,Point
    for _ in range(2):
        added=[]
        for poly in polygons:
            outline=list(poly.exterior.coords)[:-1];mapped=[]
            for angle in angles:
                d=math.cos(angle),math.sin(angle);r=ray_radius(outline,center,d);mapped.append((center[0]+d[0]*r,center[1]+d[1]*r))
            boundary=Polygon(mapped).boundary
            for x,y in outline:
                if boundary.distance(Point(x,y))>.0015:added.append(round(math.atan2(y-center[1],x-center[0]),8))
        if not added:break
        angles=sorted(set(angles+added))
    rings=[];smooth=[]
    for poly,z in zip(polygons,zs):
        points=[];outline=list(poly.exterior.coords)[:-1]
        for angle in angles:
            d=math.cos(angle),math.sin(angle);r=ray_radius(outline,center,d)
            points.append(rigid_xy(params,(center[0]+d[0]*r,center[1]+d[1]*r),z+origin,inverse=True))
        rings.append(polygon_wire(points,z));smooth.append(fitted_profile_wire(points,z))
    if all(w is not None for w in smooth) and len({len(w.Edges()) for w in smooth})==1:return smooth
    return rings


def oval_entry_regions(params,details,origin=0):
    """Opposite-skin branches of accepted oval windows, kept open after resizing."""
    import cadquery as cq
    from core import planar_vase_loft,vase_parameters
    v=vase_parameters(params);slope=math.tan(math.radians(float(params['rib_angle'])))
    pad=4*max(params['root_chord'],params['span']);regions=[];kinds=[]
    for item in details:
        mirrored=item.get('famiglia')=='specchiata';rate=(-1/slope-params['sweep']/params['span']) if mirrored else (1/slope+params['sweep']/params['span'])
        cx,cy,cz=item['centro'];half=(item['fine_z']-item['inizio_z'])/2;half_x=v['fessura_vaso']*math.sqrt(1+rate*rate)
        frames=[]
        for i in range(33):
            angle=math.pi*(1-i/32);z=cz+half*math.cos(angle);height=max(v['legamento']/2,item['altezza']/2*math.sin(angle))
            x=cx+rate*(z-cz);y0,y1=(-pad,cy-height) if mirrored else (cy+height,pad)
            frames.append([cq.Vector(xx,y,z-origin) for xx,y in ((x-half_x,y0),(x+half_x,y0),(x+half_x,y1),(x-half_x,y1))])
        regions.append(planar_vase_loft(cq,frames));kinds.append('lower' if mirrored else 'upper')
    return regions,kinds


def live_ribs(solid,full,width):
    """Continue the actual angled slit volumes, shortening their blind ends to the new skin."""
    cuts=[];types=getattr(solid,'_joiner_rib_types',[]);bounds=full.BoundingBox()
    opposites=getattr(solid,'_joiner_opposite_entries',[]);opposite_types=getattr(solid,'_joiner_opposite_types',[])
    for rib,kind in zip(getattr(solid,'_joiner_ribs',[]),types):
        bb=rib.BoundingBox()
        if bb.zmax<bounds.zmin or bb.zmin>bounds.zmax:continue
        local=rib.intersect(z_box(full,bounds.zmin-1e-5,bounds.zmax+1e-5))
        if not local.Solids():continue
        branches=[]
        for entry,entry_kind in zip(opposites,opposite_types):
            eb=entry.BoundingBox()
            if entry_kind==kind or eb.zmax<bounds.zmin or eb.zmin>bounds.zmax or eb.xmax<bb.xmin or eb.xmin>bb.xmax:continue
            part=local.intersect(entry)
            if part.Solids() and part.Volume()>1e-9:branches.append((part,entry_kind))
        primary=local.cut(*(p for p,k in branches),tol=1e-6) if branches else local
        for part,side in [(primary,kind)]+branches:
            if not part.Solids():continue
            mask=full.translate((0,1.3*width if side=='upper' else -1.3*width,0))
            clipped=part.intersect(mask)
            if clipped.Solids() and clipped.Volume()>1e-9:cuts.append(clipped)
    zone=z_box(full,bounds.zmin-1e-4,bounds.zmax+1e-4)
    masks={'lower':full.translate((0,-1.3*width,0)),'upper':full.translate((0,1.3*width,0))}
    for cutter,kind in zip(solid._joiner_cutters,solid._joiner_cut_types):
        bb=cutter.BoundingBox()
        if bb.zmax<bounds.zmin or bb.zmin>bounds.zmax:continue
        local=cutter.intersect(zone)
        if not local.Solids():continue
        if kind in masks:
            mb=masks[kind].BoundingBox();bb=local.BoundingBox()
            if bb.ymax<mb.ymin or bb.ymin>mb.ymax or bb.xmax<mb.xmin or bb.xmin>mb.xmax:continue
            local=local.intersect(masks[kind])
        if local.Solids():cuts.append(local)
    return cuts


def anchoring_collar(solid,params,male,cut,depth,width,origin):
    """Print an internal C collar below the shoulder, connected to the outer skin.

    The collar outline is already the tongue outline: it continues across the
    cut without a radial jump. A radial entry joins the single extrusion path
    to the wing skin; the gap in the C preserves a connected inverse solid.
    """
    import cadquery as cq
    from shapely.geometry import box,LineString,GeometryCollection,Polygon
    from shapely.ops import unary_union
    from core import ordered_vase_loft,vase_parameters
    envelope=solid._joiner_envelope;gap=vase_parameters(params)['fessura_vaso']
    center=male.representative_point();cx,cy=center.x,center.y
    zs=[cut-depth,cut]
    inner=ordered_vase_loft(cq,coherent_wires([male,male],zs,params,origin))
    cuts=live_ribs(solid,inner,width)
    cuts=[c.intersect(inner) for c in cuts]
    cuts=[c for c in cuts if c.Solids() and c.Volume()>1e-9]
    # Never hide a rib opening behind the solid bridge of the C collar.
    # Guard the entry positions across the entire underlap before placing it.
    occupied=[]
    for z in (cut-depth+.01,cut-depth/2,cut-.01):
        for cutter in cuts:
            bb=cutter.BoundingBox()
            if not bb.zmin<z<bb.zmax:continue
            for wire in cq.Workplane('XY').add(cutter).section(z).val().Wires():
                points=[rigid_xy(params,p,z+origin) for p in wire_points(wire)]
                face=Polygon(points)
                # Guard volumes may have tangential/coplanar edge loops: use
                # a conservative hull for placement only, never alter the CAD.
                if not face.is_valid:face=face.convex_hull
                occupied.append(face)
    guarded=unary_union(occupied).buffer(1.5*width) if occupied else GeometryCollection()
    top=cy+ray_radius(list(male.exterior.coords)[:-1],(cx,cy),(0,1))
    entry=box(cx-gap/2,top+gap/4,cx+gap/2,envelope.BoundingBox().ymax+4*width)
    rim=male.boundary.buffer(2*gap);bridge=None;bridge_angle=None
    radius=2*max(male.bounds[2]-male.bounds[0],male.bounds[3]-male.bounds[1])
    for angle in [math.pi,0]+[math.pi*k/12 for k in range(24)]:
        end=(cx+radius*math.cos(angle),cy+radius*math.sin(angle))
        candidate=LineString([(cx,cy),end]).buffer(1.5*width,cap_style=2)
        if candidate.intersects(entry):continue
        if candidate.intersection(rim).intersects(guarded):continue
        bridge=candidate;bridge_angle=math.degrees(angle);break
    if bridge is None:raise ValueError('Nervature troppo vicine per ancorare il collare: sposta leggermente il taglio.')
    arc=offset_face(male,gap).difference(male).difference(bridge)
    groove_poly=arc.union(entry)
    if groove_poly.geom_type!='Polygon' or groove_poly.interiors or not groove_poly.is_valid:
        raise ValueError('Collare di ancoraggio non realizzabile sul profilo: sposta il taglio o riduci l’offset.')
    # Use the exact same fitted inner surface as the tongue. A polygonal
    # approximation here can touch that surface and leave a microscopic
    # zero-thickness seam after the shoulder is fused.
    outer=ordered_vase_loft(cq,coherent_wires([offset_face(male,gap)]*2,zs,params,origin))
    def prism(poly):
        points=list(poly.exterior.coords)[:-1]
        return ordered_vase_loft(cq,[polygon_wire([rigid_xy(params,p,z+origin,inverse=True) for p in points],z) for z in zs])
    groove=outer.cut(inner).cut(prism(bridge)).fuse(prism(entry))
    collar=envelope.intersect(z_box(envelope,cut-depth,cut))
    collar=collar.cut(groove,*cuts,tol=1e-6)
    return valid(collar,'Ancoraggio della linguetta'),dict(inizio=cut-depth,fine=cut,profondita=depth,ponte_minimo=3*width,angolo_ponte=bridge_angle,collare_interno_collegato_alla_pelle=True)


def female_supports(solid,params,region,cut,length,safety,width,gap):
    """Separate, one-line blades in print coordinates, with clearance from the skin."""
    import cadquery as cq
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union

    finish=cut+length+safety
    height=finish-gap-cut
    origin=getattr(solid,'_washout_origin',0.)
    targets=[(bore,'bore') for bore,kind in zip(solid._joiner_cutters,solid._joiner_cut_types) if kind=='bore']
    targets.extend(zip(solid._joiner_ribs,solid._joiner_rib_types))
    footprints=[]
    for target,kind in targets:
        bounds=target.BoundingBox()
        if not bounds.zmin<finish<bounds.zmax:continue
        for wire in cq.Workplane('XY').add(target).section(finish+1e-5).val().Wires():
            face=Polygon([rigid_xy(params,p,finish+origin) for p in wire_points(wire)])
            if not face.is_valid or face.area<1e-8:continue
            if kind=='bore':
                # The printed tube wall lies outside the bore. Match its
                # complete outline, including inclined or washed-out bores.
                footprints.append((face.buffer(width).difference(face),kind))
            else:
                corners=list(face.minimum_rotated_rectangle.exterior.coords)[:4]
                sides=[LineString((corners[i],corners[(i+1)%4])) for i in range(4)]
                short=min(range(4),key=lambda i:sides[i].length)
                axis=LineString([sides[i].interpolate(.5,normalized=True) for i in (short,(short+2)%4)])
                footprints.append((axis.buffer(width/2,cap_style=2),kind))
    if not footprints:return [],[]

    # Reserve one extrusion width for the printed skin and the requested gap.
    # Intersect the usable interior at all heights so blades stay vertical.
    available=None
    steps=max(2,math.ceil(height/.2))
    for i in range(steps+1):
        z=cut+max(1e-5,height*i/steps)
        face=world_face(params,section_wire(region,z),z+origin).buffer(-width-gap-.01)
        available=face if available is None else available.intersection(face)
        if available.is_empty:break
    blades=[]
    occupied=[]
    records=[]
    for footprint,kind in footprints:
        clipped=footprint.intersection(available)
        if occupied:clipped=clipped.difference(unary_union(occupied).buffer(gap))
        if kind=='bore':
            if footprint.difference(clipped).area>1e-6:
                raise ValueError(f'Taglio Z={cut:g}: il supporto anulare della baionetta non entra con il gap richiesto. Riduci il gap o sposta il taglio.')
            clipped=footprint
        for face in getattr(clipped,'geoms',[clipped]):
            if face.geom_type!='Polygon' or face.area<2*width*width:continue
            outline=polygon_wire(list(face.exterior.coords)[:-1],0.)
            holes=[polygon_wire(list(hole.coords)[:-1],0.) for hole in face.interiors]
            blades.append(valid(cq.Solid.extrudeLinear(outline,holes,cq.Vector(0,0,height)),'Supporto removibile'))
            occupied.append(face)
            records.append(dict(tipo='anello_baionetta' if kind=='bore' else 'lama_nervatura',
                inizio_z=cut,fine_z=cut+height,gap_assiale=gap,gap_pelle=gap,larghezza_parete=width))
    return blades,records


def aileron_end_joiner_envelope(solid,params,cut,depth,length):
    """Keep the male on material existing below the end of the aileron recess.

    Only the virtual male profile continues the hinge face beyond the recess.
    The female and the aerodynamic outer envelope remain completely unchanged.
    """
    from core import aileron_parameters,aileron_axial_bounds,wing_section_at,ordered_vase_loft
    import cadquery as cq
    envelope=solid._joiner_envelope
    if params.get('_componente_esportazione','ala')!='ala':return envelope,None
    a=aileron_parameters(params)
    if not a:return envelope,None
    end=aileron_axial_bounds(a)['cut_end']
    if abs(cut-end)>1e-5:return envelope,None
    start=a['inizio_alettone'];nominal_end=start+a['lunghezza_alettone']
    hinges=[]
    for z,width in ((start,a['larghezza_alettone_radice']),(nominal_end,a['larghezza_alettone_estremita'])):
        chord,lead,_=wing_section_at(params,z);hinges.append(lead+chord-width)
    bounds=envelope.BoundingBox();pad=max(bounds.xlen,bounds.ylen,params['span'])+10
    frames=[]
    for z in (cut-depth-.01,cut+length+.01):
        fraction=(z-start)/(nominal_end-start)
        x=hinges[0]+(hinges[1]-hinges[0])*fraction-a['gioco_alettone']/2
        frames.append(polygon_wire([(x,-pad),(bounds.xmax+pad,-pad),(bounds.xmax+pad,pad),(x,pad)],z))
    virtual=envelope.cut(ordered_vase_loft(cq,frames))
    return virtual,dict(quota_fine_scasso=end,linguetta_limitata_alla_parte_comune=True,
        profilo_esterno_femmina_conservato=True,inizio_pezzo_terminale_sul_taglio=True)


def check_profile_boundaries(params,cuts):
    from core import aileron_parameters,aileron_axial_bounds,vase_parameters
    if params.get('_componente_esportazione','ala')!='ala':return
    settings=joiner_parameters(params)
    if not settings:return
    a=aileron_parameters(params)
    if not a:return
    end=aileron_axial_bounds(a)['cut_end'];width=max(settings['NozzleWidth'],vase_parameters(params)['larghezza_linea_vaso']);depth=max(3*width,2*settings['ShrinkOffset'])
    for cut in cuts:
        if abs(cut-end)<=1e-5:continue
        if cut-depth<end<cut+settings['JoinerLength']+max(width,settings['FemaleRibMargin']):
            raise ValueError(f'Taglio Z={cut:g}: la zona di giunzione attraversa la fine dello scasso alettone a Z={end:g} mm. '
                f'Per iniziare la stampa della punta senza lo sbalzo dello scasso, imposta esattamente Z={end:g} mm (pulsante Taglio a fine scasso). In alternativa, sposta il taglio almeno a Z={math.ceil((end+depth+.01)*10)/10:g} mm oppure prima di Z={end-settings["JoinerLength"]-max(width,settings["FemaleRibMargin"])-.01:g} mm.')


def build_joint(solid,params,cut,settings,origin):
    import cadquery as cq
    from core import ordered_vase_loft,vase_parameters
    envelope=solid._joiner_envelope
    length=settings['JoinerLength'];clear=settings['JoinerClearance'];shrink=settings['ShrinkOffset']
    width=max(settings['NozzleWidth'],vase_parameters(params)['larghezza_linea_vaso'])
    safety=max(width,settings['FemaleRibMargin']);finish=cut+length+safety
    anchor_depth=max(3*width,2*shrink)
    check_feature_conflicts(solid,cut,finish,cut-anchor_depth)
    profile_envelope,end_joiner=aileron_end_joiner_envelope(solid,params,cut,anchor_depth,length)
    # Local normal offsets: no intersection of profiles and no additional tip contraction.
    count=max(16,math.ceil(length/.5));levels=[length*i/count for i in range(count+1)]
    originals=[];polygons=[];inners=[]
    for t in levels:
        f=world_face(params,section_wire(profile_envelope,cut+t),cut+t+origin)
        receiver=world_face(params,section_wire(envelope,cut+t+(1e-5 if end_joiner and t==0 else 0)),cut+t+origin) if end_joiner else f
        originals.append(f);polygons.append(offset_face(f,-shrink).simplify(.002,preserve_topology=True));inners.append(offset_face(receiver,-width))
    for i,male_i in enumerate(polygons):
        for j in range(i+1):
            fit_clearance=clear if j==i else min(clear,.01)
            candidate=offset_face(male_i,fit_clearance) if fit_clearance else male_i
            if candidate.difference(inners[j].buffer(.005)).area>1e-5:
                raise ValueError(f'Taglio Z={cut:g}: il profilo con distacco uniforme non scorre nella femmina tra Z={cut+levels[j]:.3f} e Z={cut+levels[i]:.3f}. '
                    'Aumenta leggermente il gioco aggiuntivo oppure sposta il taglio; il profilo non viene ristretto automaticamente.')
    male=polygons[0]
    if offset_face(male,-width/2).area<width*width:raise ValueError('Linguetta troppo sottile per la linea selezionata.')
    full=ordered_vase_loft(cq,coherent_wires(polygons,[cut+t for t in levels],params,origin))
    distances=[]
    for reference,poly in zip(originals,polygons):
        distances.extend(reference.boundary.distance(poly.exterior.interpolate(i/180,normalized=True)) for i in range(180))
    if max(abs(d-shrink) for d in distances)>.012:raise ValueError('Offset locale non uniforme entro la tolleranza: aumenta il gioco o sposta il taglio.')
    cuts=live_ribs(solid,full,width)
    tongue=valid(full.cut(*cuts,tol=1e-6) if cuts else full,'Linguetta')
    collar,anchor_report=anchoring_collar(solid,params,male,cut,anchor_depth,width,origin)
    female_region=envelope.intersect(z_box(envelope,cut,finish));supports=[];blades=[];socket=None
    if settings['FemaleSupportEnabled']:
        blades,supports=female_supports(solid,params,female_region,cut,length,safety,width,settings['FemaleSupportGap'])
        if blades:
            zs=[cut+(finish-cut)*i/count for i in range(count+1)]
            inner=[offset_face(world_face(params,section_wire(female_region,min(finish-1e-5,max(cut+1e-5,z))),z+origin),-width) for z in zs]
            zs[0]-=.01
            socket=ordered_vase_loft(cq,coherent_wires(inner,zs,params,origin))
    female_region=valid(female_region,'Innesto femmina')
    return dict(tongue=tongue,envelope=full,collar=collar,anchor_depth=anchor_depth,female=female_region,cut=cut,finish=finish,blades=blades,socket=socket,
        report=dict(quota_taglio=cut,lunghezza=length,margine_nervature=safety,
            shrink_offset=shrink,gioco_minimo=clear,gioco_inserimento_richiesto=min(clear,.01),offset_femmina_verso_interno=shrink-clear,
            fine_scasso=end_joiner,superficie_maschio=male.area,profilo_comune_per_inserimento=bool(end_joiner),offset_locale_uniforme=True,distacco_minimo=min(distances),distacco_massimo=max(distances),campioni_inserimento=count+1,raccordo_radice=anchor_report,nervature_proseguite_su_piani_originali=True,
            supporto=settings['FemaleSupportEnabled'],gap_supporto=settings['FemaleSupportGap'],supporti_generati=supports,
            nota='Femmina libera da nervature nel tratto di innesto. Le lame removibili sono esportate separatamente, con distacco dalla pelle e dai rinforzi.'))


def apply_joiners(solid,params,pieces,cuts,progress=None):
    from core import validate_vase_sections
    import cadquery as cq
    settings=joiner_parameters(params)
    if not settings:return pieces
    check_profile_boundaries(params,cuts)
    if not cuts:raise ValueError('Attiva almeno un piano di taglio per usare le giunzioni.')
    if not hasattr(solid,'_joiner_envelope'):raise RuntimeError('Involucro per le giunzioni non disponibile: rigenera il componente.')
    if params.get('_componente_esportazione')=='alettone' and enabled(params.get('chiudi_estremita_alettone','0')):
        raise ValueError('Disattiva le chiusure dell’alettone per applicare le giunzioni in Spiral Vase.')
    # Components use local Z; washout of ailerons uses their original wing origin.
    offset=getattr(solid,'_washout_origin',0.)
    validate_joiner_layout(cuts,pieces[-1]['end'],settings,float(params.get('larghezza_linea_vaso',.55)))
    width=max(settings['NozzleWidth'],float(params.get('larghezza_linea_vaso',.55)))
    safety=max(width,settings['FemaleRibMargin'])
    anchor_depth=max(3*width,2*settings['ShrinkOffset'])
    for i,piece in enumerate(pieces):
        if i<len(pieces)-1 and piece['end']-piece['start']<=anchor_depth+(settings['JoinerLength']+safety if i else 0):
            raise ValueError(f'Pezzo {i+1} troppo corto per l’ancoraggio della linguetta e il ricevente.')
    joints=[]
    for i,cut in enumerate(cuts):
        joints.append(build_joint(solid,params,cut,settings,offset))
        if progress:progress(i+1,len(cuts)+len(pieces))
    for i,piece in enumerate(pieces):
        part=piece['solid'];start=piece['start'];height=piece['end']-start;reports=[]
        if i:
            j=joints[i-1];extent=j['finish']-start
            part=part.cut(z_box(part,-1,extent)).fuse(j['female'].translate((0,0,-start)),tol=1e-6)
            piece['support_blades']=j['blades']
            reports.append(dict(lato='femmina',**j['report']))
        if i<len(joints):
            j=joints[i]
            anchor_start=j['cut']-j['anchor_depth']-start
            if anchor_start<=0:raise ValueError(f'Pezzo {i+1} troppo corto per ancorare la linguetta.')
            part=part.cut(z_box(part,anchor_start,piece['end']-start+1)).fuse(j['collar'].translate((0,0,-start)),j['tongue'].translate((0,0,-start)),tol=1e-6)
            reports.append(dict(lato='maschio',**j['report']));height+=settings['JoinerLength']
        part=valid(part,f'Pezzo {i+1}')
        if i and joints[i-1]['socket'] is not None:
            hollow=valid(part.cut(joints[i-1]['socket'].translate((0,0,-start)),tol=1e-6),'Femmina aperta per supporti')
            for attr in ('_washout_params','_washout_origin'):
                if hasattr(piece['solid'],attr):setattr(hollow,attr,getattr(piece['solid'],attr))
            piece['supported_body']=hollow
        for attr in ('_washout_params','_washout_origin','_oval_params'):
            if hasattr(piece['solid'],attr):setattr(part,attr,getattr(piece['solid'],attr))
        extras=[]
        for j in joints:
            extras.extend(t-start+d for t in (j['cut']-j['anchor_depth'],j['cut'],j['cut']+settings['JoinerLength'],j['finish']) for d in (-.01,.01))
        from mesh_checks import inherit_sections
        inherit_sections(piece['solid'],part,height=height)
        piece.update(solid=part,print_height=height,joiners=reports,
            sections=validate_vase_sections(cq,part,height,samples=17,extra_z=extras))
        if progress:progress(len(cuts)+i+1,len(cuts)+len(pieces))
    return pieces
