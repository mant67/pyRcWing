"""Shared straight spar axes, in root coordinates (X chord, Z span)."""
import math
from planform import planform_section


def spar_automatic(spar):
    value=spar.get('angle_auto')
    if value is None:return not str(spar.get('angle_deg','')).strip()
    return str(value).strip().lower() in ('1','true','yes','on')


def legacy_spar_angle(params,position):
    u=float(str(position).replace(',','.'))/100
    dx=planform_section(params,params['span'])[1]+u*(params['tip_chord']-params['root_chord'])
    return math.degrees(math.atan2(dx,params['span']))


def spar_axis(params,spar):
    from core import camber_thickness,airfoil_tip_code
    span,cr,ct=params['span'],params['root_chord'],params['tip_chord'];u=spar['position']/100
    yc,_=camber_thickness(u,params['airfoil']);root=(u*cr,yc*cr,0.)
    if spar_automatic(spar):
        yt,_=camber_thickness(u,airfoil_tip_code(params))
        end=(planform_section(params,span)[1]+u*ct,yt*ct,span)
    else:
        # Manual rotation stays in the root X/Z plane: zero is its normal Z.
        end=(root[0]+math.tan(math.radians(spar['angle_deg']))*span,root[1],span)
    delta=tuple(b-a for a,b in zip(root,end))
    return root,delta


def has_manual_spar_angles(params):
    if params.get('_componente_esportazione')=='alettone':return False
    return any(not spar_automatic(s) for s in params.get('spars',[]))
