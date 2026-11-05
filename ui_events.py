"""Translate actual text mutations, never poll or redraw an idle interface."""
import functools
import tkinter as tk
from tkinter import ttk
_installed=False

def owner(widget):
    try:
        root=widget._root()
        return root if getattr(root,'_menus_ready',False) and not root._translating else None
    except (AttributeError,tk.TclError):return None

def text(root,key,value):
    source=root._translated_sources.get(str(value),str(value));rendered=root.tr(source)
    root._translation_cache[key]=(source,rendered)
    if source!=rendered:root._translated_sources[rendered]=source
    return rendered

def install_ui_notifications():
    global _installed
    if _installed:return
    _installed=True
    original_init=tk.BaseWidget.__init__
    @functools.wraps(original_init)
    def init(widget,*args,**kwargs):
        original_init(widget,*args,**kwargs)
        root=owner(widget)
        if root is not None:
            if 'text' in widget.keys() and widget.winfo_class()!='Menu':
                raw=widget.cget('text')
                if raw:widget.configure(text=raw)
            root._schedule_ui_update()
    tk.BaseWidget.__init__=init

    original_configure=tk.Misc.configure
    @functools.wraps(original_configure)
    def configure(widget,cnf=None,**kwargs):
        root=owner(widget);options=dict(cnf) if isinstance(cnf,dict) else {}
        options.update(kwargs)
        if root is not None and 'text' in options:
            options['text']=text(root,('text',str(widget)),options['text'])
            if str(widget.cget('text'))==str(options['text']):
                options.pop('text')
                if not options:return None
        if isinstance(cnf,dict):result=original_configure(widget,options)
        else:result=original_configure(widget,cnf,**(options if options else kwargs))
        if root is not None and 'textvariable' in options:root._schedule_ui_update()
        return result
    tk.Misc.configure=tk.Misc.config=configure

    original_create=tk.Canvas._create
    @functools.wraps(original_create)
    def create(widget,kind,args,kw):
        root=owner(widget);source=None
        if root is not None and kind=='text' and 'text' in kw:
            kw=dict(kw);source=root._translated_sources.get(str(kw['text']),str(kw['text']));kw['text']=root.tr(source)
        item=original_create(widget,kind,args,kw)
        if source is not None:
            rendered=str(kw['text']);root._translation_cache[('canvas',str(widget),item)]=(source,rendered)
            if source!=rendered:root._translated_sources[rendered]=source
        return item
    tk.Canvas._create=create

    original_itemconfigure=tk.Canvas.itemconfigure
    @functools.wraps(original_itemconfigure)
    def itemconfigure(widget,tagOrId,cnf=None,**kwargs):
        root=owner(widget);options=dict(cnf) if isinstance(cnf,dict) else {};options.update(kwargs)
        if root is not None and 'text' in options:
            raw=options['text'];items=widget.find_withtag(tagOrId)
            for item in items:
                if widget.type(item)=='text':text(root,('canvas',str(widget),item),raw)
            options['text']=root.tr(root._translated_sources.get(str(raw),str(raw)))
            if items and all(widget.type(i)=='text' and widget.itemcget(i,'text')==options['text'] for i in items):
                options.pop('text')
                if not options:return None
        return original_itemconfigure(widget,tagOrId,options) if isinstance(cnf,dict) else original_itemconfigure(widget,tagOrId,cnf,**options)
    tk.Canvas.itemconfigure=tk.Canvas.itemconfig=itemconfigure

    original_delete=tk.Canvas.delete
    @functools.wraps(original_delete)
    def delete(widget,*tags):
        root=owner(widget)
        if root is not None:
            for tag in tags:
                for item in widget.find_withtag(tag):root._translation_cache.pop(('canvas',str(widget),item),None)
        return original_delete(widget,*tags)
    tk.Canvas.delete=delete

    original_insert=ttk.Treeview.insert
    @functools.wraps(original_insert)
    def insert(widget,parent,index,iid=None,**kw):
        root=owner(widget);source=kw.get('values')
        if root is not None and source is not None:kw['values']=[root.tr(str(v)) for v in source]
        item=original_insert(widget,parent,index,iid,**kw)
        if root is not None:
            if source is not None:
                for i,v in enumerate(source):text(root,('cell',str(widget),item,i),v)
            root._schedule_ui_update()
        return item
    ttk.Treeview.insert=insert

    original_item=ttk.Treeview.item
    @functools.wraps(original_item)
    def tree_item(widget,item,option=None,**kw):
        root=owner(widget)
        if root is not None and 'values' in kw:
            kw['values']=[text(root,('cell',str(widget),item,i),v) for i,v in enumerate(kw['values'])]
            if tuple(original_item(widget,item,'values'))==tuple(kw['values']):
                kw.pop('values')
                if not kw and option is None:return None
        return original_item(widget,item,option,**kw)
    ttk.Treeview.item=tree_item

    original_heading=ttk.Treeview.heading
    @functools.wraps(original_heading)
    def heading(widget,column,option=None,**kw):
        root=owner(widget)
        if root is not None and 'text' in kw:
            kw['text']=text(root,('heading',str(widget),column),kw['text'])
            if original_heading(widget,column,'text')==kw['text']:
                kw.pop('text')
                if not kw and option is None:return None
        return original_heading(widget,column,option,**kw)
    ttk.Treeview.heading=heading

    original_tree_delete=ttk.Treeview.delete
    @functools.wraps(original_tree_delete)
    def tree_delete(widget,*items):
        result=original_tree_delete(widget,*items);root=owner(widget)
        if root is not None:root._schedule_ui_update()
        return result
    ttk.Treeview.delete=tree_delete
