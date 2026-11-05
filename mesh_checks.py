"""Fast section checks on the exact final, closed STL mesh. Same planned Zs.
Topology is joined by welded mesh edge IDs, never by rounding XY gaps away.
"""
from contextvars import ContextVar
from contextlib import contextmanager
import math,time
_MODE=ContextVar('wing_final_mesh_checks',default=False)

@contextmanager
def final_mesh_checks(enabled=True):
 token=_MODE.set(bool(enabled))
 try:yield
 finally:_MODE.reset(token)

def plan_sections(solid,span,quotes):
 if not _MODE.get():return None
 quotes=sorted(set(float(z) for z in list(getattr(solid,'_vase_check_quotes',[]))+list(quotes) if 1e-5<float(z)<span-1e-5))
 solid._vase_check_quotes=quotes
 return [dict(z=z,contorni=None,verifica='programmata sulla mesh STL finale') for z in quotes]

def inherit_sections(source,target,offset=0.,height=None):
 quotes=[z-offset for z in getattr(source,'_vase_check_quotes',[])]
 if height is not None:quotes=[z for z in quotes if 1e-5<z<height-1e-5]
 if quotes:target._vase_check_quotes=quotes

def mesh_section_checks(points,triangles,quotes,progress=None):
 import numpy as np
 start=time.perf_counter();p=np.asarray(points,dtype=np.float64);t=np.asarray(triangles,dtype=np.int64);zs=p[t,2]
 lo=zs.min(axis=1);hi=zs.max(axis=1);height=float(p[:,2].max());bottom=float(p[:,2].min())
 quotes=sorted(set(float(z) for z in quotes if bottom+1e-5<float(z)<height-1e-5))
 def count(z):
  indices=np.flatnonzero((lo<=z)&(hi>=z));segments=set()
  for index in indices:
   tri=t[index];values=zs[index];nodes=[]
   for i,j in ((0,1),(1,2),(2,0)):
    if (values[i]<z)==(values[j]<z):continue
    a,b=int(tri[i]),int(tri[j])
    if values[i]==z:key=(-1,a)
    elif values[j]==z:key=(-1,b)
    else:key=(min(a,b),max(a,b))
    if key not in nodes:nodes.append(key)
   if len(nodes)==2:segments.add(tuple(sorted(nodes)))
  if not segments:return 0,False
  links={}
  for a,b in segments:
   links.setdefault(a,set()).add(b);links.setdefault(b,set()).add(a)
  closed=all(len(v)==2 for v in links.values());unseen=set(links);n=0
  while unseen:
   n+=1;todo=[unseen.pop()]
   while todo:
    for other in links[todo.pop()]:
     if other in unseen:unseen.remove(other);todo.append(other)
  return n,closed
 result=[]
 for i,z in enumerate(quotes):
  n,closed=count(z);item=dict(z=z,contorni=n,contorno_chiuso=closed,metodo='mesh finale saldata')
  if n!=1 or not closed:
   adjacent=[count(z+d) for d in (-1e-5,1e-5) if bottom<z+d<height]
   if adjacent and all(v==(1,True) for v in adjacent):item.update(contorni=1,contorno_chiuso=True,contorni_sul_piano=n,transizione_coplanare=True)
   else:raise RuntimeError(f'Spiral Vase non valido sulla mesh finale a Z={z:.5f}: {n} contorni, chiusura={closed}. Esportazione bloccata.')
  result.append(item)
  if progress:progress('mesh_sections',i+1,len(quotes))
 return result,time.perf_counter()-start
