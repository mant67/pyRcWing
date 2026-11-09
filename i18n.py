"""Display-only Italian/English translation; configuration keys stay unchanged."""
# File revision: 12
import re,functools
import tkinter as tk
from tkinter import messagebox,filedialog

_PAIRS='''Preferenze => Preferences
Lingua => Language
Guida => Help
Importa… => Import…
Esporta… => Export…
Esci… => Exit…
Esci => Exit
Uso rapido => Quick start
Informazioni => About
Modifiche non salvate => Unsaved changes
Ci sono parametri non salvati. Vuoi salvarli prima di continuare? => There are unsaved parameters. Save them before continuing?
Vuoi chiudere pyRcWing? => Close pyRcWing?
Operazione in corso => Operation in progress
Attendi il termine dell’operazione prima di uscire. => Wait for the current operation to finish before exiting.
Impossibile salvare la preferenza lingua. => Could not save the language preference.
Generatore parametrico di ali RC e componenti per la stampa 3D. => Parametric RC wing and component generator for 3D printing.
← Indietro => ← Back
Avanti → => Next →
Stampa zero retrazioni => Zero-retraction printing
Geometria => Geometry
Geometria ala => Wing geometry
Punta => Wingtip
Longheroni => Spars
Alettone e chiusure => Aileron and end caps
Asole cerniere => Hinge slots
Diedro e raccordo => Dihedral and centre connector
Diedro e raccordo centrale => Dihedral and centre connector
Sezionatura 2D => 2D sectioning
Riepilogo ed esportazione => Summary and export
Configurazione ala => Wing configuration
Riepilogo configurazione => Configuration summary
Importa configurazione… => Import configuration…
Esporta configurazione… => Export configuration…
Importa configurazione ala => Import wing configuration
Esporta configurazione ala => Export wing configuration
Configurazione salvata => Configuration saved
Configurazione caricata => Configuration loaded
Configurazione non salvata => Configuration not saved
Configurazione non caricata => Configuration not loaded
Esportazione configurazione => Configuration export
Importazione configurazione => Configuration import
Esportazione => Export
Importazione => Import
Tutti i file => All files
File STL => STL files
Apri cartella output… => Open output folder…
Adatta valori all’ugello => Match values to nozzle
Verifica G-code PrusaSlicer… => Check PrusaSlicer G-code…
Verifica G-code PrusaSlicer — non esegue la stampa => PrusaSlicer G-code check — does not print
Verifica opzionale zero retrazioni con PrusaSlicer durante l’esportazione => Optional zero-retraction check with PrusaSlicer during export
Diametro ugello (mm) => Nozzle diameter (mm)
Larghezza linea vaso (mm) => Vase extrusion width (mm)
Altezza strato prova (mm) => Test layer height (mm)
Fessura invisibile (mm) => Invisible slit (mm)
Spiral Vase a fessure — modalità sperimentale => Slit-based Spiral Vase — experimental mode
Nervature e alleggerimenti => Ribs and lightening holes
Crea nervature interne => Create internal ribs
Nervature specchiate (ala e alettone) => Mirrored ribs (wing and aileron)
Alleggerimenti con fori ovali => Oval lightening holes
Numero ovali per nervatura => Number of ovals per rib
Lunghezza ovale (mm) => Oval length (mm)
Altezza ovale (mm) => Oval height (mm)
Passo nervature (mm) => Rib spacing (mm)
Angolo diagonali (°) => Diagonal angle (°)
NACA radice (4 cifre) => Root NACA (4 digits)
NACA estremità (4 cifre) => Tip NACA (4 digits)
Semiala Z senza punta (mm) => Half-span Z without wingtip (mm)
Corda radice (mm) => Root chord (mm)
Corda estremità (mm) => Tip chord (mm)
Freccia bordo attacco (mm) => Leading-edge sweep (mm)
Punti profilo => Airfoil points
Stazioni lungo Z => Stations along Z
Pianta alare => Wing planform
Linea centrale ellisse (% corda) => Ellipse centreline (% chord)
Svergolamento progressivo dell’ala (washout) => Progressive wing washout
Washout finale (gradi) => Final washout (degrees)
Inizio dalla radice (mm) => Start from root (mm)
Perno (% corda dal bordo d’attacco) => Pivot (% chord from leading edge)
Aggiungi punta ellittica (ispirata allo Spitfire) => Add elliptical wingtip (Spitfire inspired)
Punta rastremata opzionale — nervature secondo la scelta iniziale => Optional tapered wingtip — ribs follow the initial setting
Lunghezza aggiuntiva Z (mm) => Added Z length (mm)
Linea centrale (% corda estremità, dal bordo d’attacco) => Centreline (% tip chord from leading edge)
Proposta dalla geometria dell’ala => Suggestion from wing geometry
Applica proposta => Apply suggestion
Longheroni — numero, posizione, diametro e lunghezza => Spars — number, position, diameter and length
Numero longheroni (0 = nessuno) => Number of spars (0 = none)
Gioco diametrale (mm) => Diametral clearance (mm)
Posizione (% corda) => Position (% chord)
Diametro (mm) => Diameter (mm)
Lunghezza Z (mm) => Z length (mm)
Inclinazione in pianta (°) => Plan-view angle (°)
Direzione => Direction
Alettone separato — esportazione dedicata => Separate aileron — dedicated export
Crea alettone separato e lascia il vano libero nell’ala => Create separate aileron and leave its recess open in the wing
Distanza dalla radice (mm) => Distance from root (mm)
Lunghezza nominale Z (mm) => Nominal Z length (mm)
Larghezza lato radice (mm) => Root-side width (mm)
Larghezza lato estremità (mm) => Tip-side width (mm)
Angolo smusso (gradi) => Bevel angle (degrees)
Gioco lungo cerniera (mm) => Hinge clearance (mm)
Gioco estremità radice (mm) => Root-end clearance (mm)
Gioco estremità punta (mm) => Tip-end clearance (mm)
Chiudi entrambe le estremità dell’alettone: sotto e sopra => Close both aileron ends: bottom and top
Spessore chiusure Z (mm) => Z end-cap thickness (mm)
Asole per le cerniere — coppie abbinate su ala e alettone => Hinge slots — matching pairs on wing and aileron
Crea asole per le cerniere => Create hinge slots
Numero coppie di asole => Number of slot pairs
Interasse Z (mm, 0 = automatico) => Z spacing (mm, 0 = automatic)
Lunghezza asole Z (mm) => Slot Z length (mm)
Altezza asole (mm) => Slot height (mm)
Profondità per lato (mm) => Depth per side (mm)
Distanza centro sotto estradosso (mm) => Centre distance below upper surface (mm)
Pareti alloggiamenti asole (mm) => Slot housing walls (mm)
Angolo rampe sostegno asole (°) => Slot support ramp angle (°)
Alloggiamento servo e sede per il futuro pannello di chiusura => Servo recess and seat for a future cover panel
Predisponi scasso servo sull’intradosso => Add servo recess on lower surface
Tipo servo: 1 = 3,7 g; 2 = 5 g; 3 = 9 g => Servo type: 1 = 3.7 g; 2 = 5 g; 3 = 9 g
Centro dalla radice (mm) => Centre from root (mm)
Centro dal bordo d’attacco locale (mm) => Centre from local leading edge (mm)
Offset verso l’intradosso (mm) => Offset towards lower surface (mm)
Larghezza corpo X (mm) => Body X width (mm)
Altezza corpo Y (mm) => Body Y height (mm)
Lunghezza corpo Z (mm) => Body Z length (mm)
Gioco per lato (mm) => Clearance per side (mm)
Larghezza battuta perimetrale (mm) => Perimeter lip width (mm)
Profondità sede coperchio (mm) => Cover seat depth (mm)
Rotazione attorno a Z => Rotation around Z
Rotazione in pianta (asse Y) => Plan-view rotation (Y axis)
Angolo attorno a Z (gradi) => Angle around Z (degrees)
Angolo in pianta (gradi) => Plan-view angle (degrees)
Ricarica misure indicative della taglia => Reload indicative size dimensions
Scasso servo disattivato. => Servo recess disabled.
Genera raccordo centrale => Generate centre connector
Dimensioni e innesti => Dimensions and sockets
Diedro per semiala (°) => Dihedral per half-wing (°)
Lunghezza innesto (mm) => Socket length (mm)
Spazio sedi e fondi (mm) => Socket and end-wall allowance (mm)
Doppio rinforzo dei longheroni => Double spar reinforcement
Nervature specchiate => Mirrored ribs
Anteprima del raccordo => Connector preview
Esporta STL raccordo intero… => Export whole connector STL…
Esporta STL ala intera… => Export whole wing STL…
Esporta STL alettone intero… => Export whole aileron STL…
Esporta ala sezionato… => Export sectioned wing…
Esporta alettone sezionato… => Export sectioned aileron…
Esporta raccordo centrale sezionato… => Export sectioned centre connector…
Z locale (mm) => Local Z (mm)
Piano Z locale (mm) => Local Z plane (mm)
Elemento => Component
Aggiungi => Add
Modifica => Edit
Editor… => Editor…
Editor profilo radice => Root airfoil editor
Editor profilo estremità => Tip airfoil editor
Libreria profili => Airfoil library
Editor pianta… => Planform editor…
Editor pianta alare => Wing planform editor
Editor punta… => Wingtip editor…
Editor punta alare => Wingtip editor
Editor alettone… => Aileron editor…
Editor alettone => Aileron editor
Sfondo condiviso da Geometria. Trascina le maniglie per modificare il componente. => Background shared from Geometry. Drag the handles to edit the component.
Libreria piante => Planform library
Salva pianta => Save planform
Nome della pianta: => Planform name:
Sostituire la pianta già salvata? => Replace the saved planform?
Pianta salvata nella libreria. => Planform saved to the library.
Note della pianta => Planform notes
Modifica pianta => Edit planform
Inserisci nodo => Insert node
Elimina nodo => Delete node
Ripristina pianta iniziale => Reset to initial planform
Ripristina vista => Reset view
Tangente terminale automatica => Automatic tip tangent
Rotella e trascinamento spostano la vista. Con Maiusc agiscono solo sullo sfondo. Tasto destro sul bordo blu per aggiungere un nodo. => Scroll to zoom and drag to pan. Hold Shift to affect only the background. Right-click a blue edge to add a node.
Importa immagine della pianta => Import planform image
Tasto destro sul bordo blu per inserire un nodo. Trascina le maniglie per modificare la pianta. => Right-click a blue edge to insert a node. Drag the handles to edit the planform.
Semiala (mm) => Half-span (mm)
Freccia (mm) => Sweep (mm)
Centro ellisse (%) => Ellipse centre (%)
Salva profilo => Save airfoil
Chiudi e applica => Close and apply
Note del profilo => Airfoil notes
Nome del profilo: => Airfoil name:
Profilo alare => Airfoil
Profilo salvato nella libreria. => Airfoil saved to the library.
Calibra => Calibrate
Rimuovi immagine => Remove image
Blocca sfondo => Lock background
Sblocca sfondo => Unlock background
Sfondo bloccato. Le maniglie restano modificabili. => Background locked. The handles remain editable.
Carica immagine… => Load image…
Ruota => Rotate
Fine rotazione => Finish rotation
Trascina la croce per spostare il pivot. Trascina altrove per ruotare. => Drag the crosshair to move the pivot. Drag elsewhere to rotate.
Trascina le maniglie per modificare il profilo o lo sfondo per spostarlo. => Drag the handles to edit the airfoil or drag the background to move it.
Inserisci un angolo di rotazione valido. => Enter a valid rotation angle.
Rotella per lo zoom dello sfondo. Tasto destro per i comandi del profilo e dello sfondo. => Use the mouse wheel to zoom the background. Right-click for airfoil and background commands.
Impostazioni editor => Editor settings
Trascina le maniglie interne. I bordi fissano la lunghezza della corda. => Drag the internal handles. The edges fix the chord length.
Profilo modificato. Premi Chiudi e applica per aggiornare l’ala. => Airfoil edited. Click Close and apply to update the wing.
Seleziona un punto all’interno dell’immagine. => Pick a point inside the image.
Scegli un secondo punto diverso dal primo. => Pick a second point different from the first.
Distanza reale tra i due punti (mm): => Actual distance between the two points (mm):
Importa immagine… => Import image…
Calibra con due punti => Calibrate with two points
Sposta sfondo => Move background
Modifica profilo => Edit airfoil
Ripristina NACA => Reset to NACA
Immagine => Image
Calibrazione => Calibration
Importa prima un’immagine raster. => Import a raster image first.
Importa immagine del profilo => Import airfoil image
Immagini raster => Raster images
Elimina => Delete
Aggiorna anteprime => Update previews
Aggiorna elenco => Update list
Svuota elemento => Clear component
Taglio a fine scasso => Cut at end of recess
Giunzioni di allineamento e incollaggio => Alignment and bonding joints
Giunzioni maschio/femmina a ogni taglio (tutti i componenti) => Male/female joints at every cut (all components)
Lunghezza linguetta (mm) => Tongue length (mm)
Gioco minimo assemblaggio (mm) => Minimum assembly clearance (mm)
Gioco aggiuntivo sulla linea (mm) => Extra clearance on extrusion width (mm)
Gap supporto removibile (mm) => Removable support gap (mm)
Riserva oltre la linguetta (mm) => Allowance beyond tongue (mm)
Supporti femmina verticali e removibili => Vertical removable female supports
Raccolta dei parametri => Collecting parameters
Verifica della configurazione => Checking configuration
Preparazione del file => Preparing file
Scrittura del file => Writing file
Lettura del file => Reading file
Ripristino dei parametri => Restoring parameters
Aggiornamento delle anteprime => Updating previews
Applicazione washout => Applying washout
Triangolazione STL => STL triangulation
Verifica chiusura e orientamento => Checking closure and orientation
Verifica dei vertici => Checking vertices
Verifica sezioni sulla mesh finale => Checking final mesh sections
Verifica zero retrazioni => Zero-retraction check
Salvataggio impostazioni e rapporti => Saving settings and reports
Scrittura del file STL => Writing STL file
Geometria invariata: riuso del modello già calcolato => Unchanged geometry: reusing the calculated model
Tagli e giunzioni invariati: riuso dei pezzi già calcolati => Unchanged cuts and joints: reusing calculated parts
Salva e ricarica tutti i pannelli, i longheroni e i piani di taglio. => Save and reload all panels, spars and cutting planes.
Queste esportazioni producono i componenti interi. Per esportare i pezzi usa il pannello Sezionatura 2D. => These exports produce whole components. Use the 2D sectioning panel to export individual pieces.
La scelta vale per ala, punta e alettone. => Applies to wing, wingtip and aileron.
Modalità zero retrazioni attiva. Le chiusure piene dell’alettone usano impostazioni dedicate. => Zero-retraction mode enabled. Solid aileron end caps use dedicated settings.
Disattivata: esporta senza PrusaSlicer mantenendo i controlli geometrici e della mesh. Attiva: richiede PrusaSlicer e blocca l’esportazione se la verifica non passa. => Disabled: export without PrusaSlicer while retaining geometry and mesh checks. Enabled: requires PrusaSlicer and blocks export if its check fails.
Senza giunzioni i tagli conservano fori e cavità. Con giunzioni la zona femmina è libera da nervature e sedi interne; servo e cerniere non possono intersecare l’innesto. Ogni pezzo è appoggiato su Z=0. => Without joints, cuts preserve holes and cavities. With joints, the female region is free of permanent ribs and internal seats; servo and hinges must not intersect the socket. Every piece rests on Z=0.
'''
CATALOG={}
for line in _PAIRS.splitlines():
    if ' => ' in line:
        a,b=line.split(' => ',1);CATALOG[a.replace('’',"'")]=b

CATALOG.update({'Vista nominale senza washout · 0° perpendicolare alla radice.': 'Nominal view without washout · 0° perpendicular to the root.', 'Longheroni entro la semiala principale': 'Spars within the main half-wing', "Sedi con lunghezze indipendenti e canali coassiali collegati al profilo. Controllare il percorso zero retrazioni nell'anteprima dello slicer.": 'Independent seat lengths and coaxial channels connected to the airfoil. Inspect the zero-retraction path in the slicer preview.', "Lunghezza lungo Z; altezza = spessore della linguetta. Distanza misurata dalla linea di cerniera sull'estradosso al centro dell'asola. Interasse 0: distribuzione uniforme con margini uguali ai bordi effettivi dell'alettone; interasse impostato: gruppo centrato con margini uguali. Rampe prima delle tasche: angolo dalla verticale Z; un angolo minore genera una rampa più lunga. Disponibili anche in Spiral Vase; le nervature si interrompono localmente presso le tasche.": 'Length runs along Z; height is the hinge tongue thickness. Distance is measured from the upper-surface hinge line to the slot centre. Spacing 0 distributes slots uniformly with equal margins at the actual aileron ends; an explicit spacing centres the group with equal margins. Ramps precede the pockets: their angle is measured from vertical Z, and smaller angles produce longer ramps. Available in Spiral Vase mode; ribs are locally interrupted at the pockets.', 'Vista X/Z della sagoma nominale, senza strutture interne. Click: aggiungi un piano; trascina una linea per spostarlo; tasto destro: elimina. Quote Z locali dalla base di ogni componente nella posizione di stampa.': 'X/Z view of nominal outlines, without internal structures. Click to add a plane; drag a line to move it; right-click to delete it. Local Z coordinates start at the base of each component in its print orientation.', 'Maniglia L: trascina in orizzontale · Centro: trascina in verticale.': 'L handle: drag horizontally · Centre: drag vertically.', "Confronto dei profili in scala comune: radice, metà apertura, estremità · allineati al bordo d'attacco": 'Airfoil comparison at a common scale: root, mid-span and tip · Aligned at the leading edge', "Maschio ancorato sotto il taglio sul pezzo inferiore, femmina sul successivo. Distacco locale uniforme: linea effettiva + gioco aggiuntivo. Il profilo viene verificato durante l'inserimento. I supporti crescono verticali fino alle nervature interrotte e vanno rimossi prima dell'incollaggio. La verifica PrusaSlicer è opzionale e si attiva nel primo pannello.": 'The male is anchored below the cut on the lower piece; the next piece carries the female socket. Local uniform offset: global extrusion width + extra clearance. Insertion is checked. Temporary supports grow vertically towards the interrupted ribs and must be removed before bonding. PrusaSlicer verification is optional and enabled in the first panel.', 'Ala orizzontale, nella stessa scala sui due assi · Vista senza washout.': 'Horizontal wing, with the same scale on both axes · View without washout.', 'Valori geometrici di partenza, modificabili con i campi o le maniglie. La proposta non modifica automaticamente la configurazione.': 'Starting geometry values, editable with fields or handles. The suggestion does not automatically change the configuration.', "25%: linea al quarto della corda. 50% riproduce la punta centrata delle versioni precedenti. 0% = bordo d'attacco; 100% = bordo d'uscita. La giunzione con la semiala rimane nella stessa posizione. Raccordo continuo e chiusura arrotondata della punta.": '25% places the centreline at quarter chord. 50% reproduces the centred wingtip of earlier versions. 0% = leading edge; 100% = trailing edge. The half-wing connection stays in place, with a continuous blend and rounded tip closure.', 'Sedi per barre/tubi inseriti dopo la stampa': 'Seats for rods/tubes inserted after printing', "Auto conserva la direzione attuale. In manuale: 0° perpendicolare alla radice; positivo verso il bordo d'uscita. Le maniglie regolano posizione e inclinazione.": 'Auto keeps the current direction. Manual: 0° is perpendicular to the root; positive angles point towards the trailing edge. Handles adjust position and angle.', 'Pianta nominale · Radice a sinistra, estremità a destra': 'Nominal planform · Root at left, tip at right', "Scasso servo sull'intradosso · posizione in pianta": 'Servo recess on lower surface · Plan-view position', 'Nervature schematiche: viola = originali · verde = specchiate': 'Schematic ribs: purple = original · green = mirrored', 'Pianta senza washout · Le sezioni a destra mantengono il washout.': 'Planform without washout · Sections at right retain washout.', "Profilo di radice e sedi derivano dalla semiala. Senza longheroni, lunghezza innesto e spazio riservato definiscono l'ingombro. Le nervature del raccordo sono indipendenti da quelle dell'ala.": 'Root airfoil and seats follow the half-wing. Without spars, socket length and reserved space define the dimensions. Connector ribs are independent of wing ribs.', 'v9.1: larghezza delle giunzioni unificata con la linea del primo pannello. PrusaSlicer opzionale. Spiral Vase sperimentale: verificare ciascun G-code e stampare prima un provino.': 'v9.1: File, Preferences and Help menus, unsaved-change protection and Italian/English interface. Experimental Spiral Vase: inspect each G-code and print a test piece first.', "Punta con nervature opzionali, sedi longheroni a lunghezza indipendente e alettone separato possono essere combinati. Il vano può terminare prima dell'estremità: l'eventuale sbalzo viene mantenuto nel modello, in attesa della futura suddivisione dell'ala. Asole cerniere disponibili anche in Spiral Vase, con interruzione locale delle nervature presso le tasche. Esporta anche impostazioni PrusaSlicer senza ritrazioni e rapporto CAD; stampare un corpo alla volta e verificare assenza di travel nel G-code e un provino prima della stampa dell'ala.": 'Optional wingtip ribs, independent spar-seat lengths and a separate aileron can be combined. The recess may end before the wingtip; any resulting overhang remains in the model. Hinge slots are also available in Spiral Vase mode, with local rib interruptions near the pockets. Slicer settings and a geometry report are exported. Print one body at a time and inspect the G-code before printing a test piece.', "Le misure iniziali sono indicative e modificabili: il peso non identifica un ingombro standard. Le distanze individuano il centro del corpo. Offset positivo sposta il servo verso l'esterno dell'intradosso: in Y il corpo va da −offset ad altezza−offset, prima della rotazione. La battuta segue il profilo inferiore; il pannello di chiusura non viene generato. Se il corpo sporge, il futuro coperchio dovrà prevedere il relativo ingombro oppure andranno adattate misure e offset. Le modalità Z e in pianta sono alternative; l'angolo inattivo viene ignorato.": 'Initial dimensions are indicative and editable: weight alone does not specify standard dimensions. Distances locate the body centre. A positive offset moves the servo out through the lower surface: before rotation, body Y runs from −offset to height−offset. The lip follows the lower profile; no cover panel is generated. If the body protrudes, the future cover must accommodate it, or the dimensions and offset must be adjusted. Z and plan-view rotation modes are mutually exclusive; the inactive angle is ignored.', 'Trascina le maniglie arancioni oppure modifica i campi. Vista nominale, senza washout.': 'Drag the orange handles or edit the fields. Nominal view without washout.', 'Salva raccordo centrale': 'Save centre connector', 'Maniglia alla radice: posizione · Maniglia finale: inclinazione.': 'Root handle: position · End handle: angle.', "Scala comune in mm · Profili allineati al bordo d'attacco prima del washout.": 'Common scale in mm · Airfoils aligned at the leading edge before washout.', "0° disattiva il washout. La rotazione cresce linearmente dall'inizio scelto fino all'estremità della semiala; la punta aggiuntiva mantiene l'angolo finale. Il perno si trova sulla linea di corda (Y=0). Un valore positivo solleva il bordo d'uscita rispetto al bordo d'attacco.": '0° disables washout. Rotation increases linearly from the selected start to the half-wing end; the added wingtip keeps the final angle. The pivot lies on the chord line (Y=0). A positive value raises the trailing edge relative to the leading edge.', 'In modalità a labirinto, con chiusure: usare il file .chiusure.ini. Superfici piene e ritrazioni disattivate; stampa a strati, con possibili spostamenti a vuoto. La chiusura superiore può essere a sbalzo.': 'For labyrinth mode with end caps, use the .chiusure.ini file. Solid surfaces and disabled retractions require layer printing, with possible travel moves. The upper cap may overhang.', "Distanza dalla radice: posizione reale del primo estremo dell'alettone, minimo metà del gioco radice; azzera il gioco per partire da Z=0. I giochi alle estremità sono separati dalla posizione e dal gioco cerniera. Il bordo d'uscita dell'alettone resta vincolato a quello dell'ala. Le quote nominali sono divise a metà: il vano si allarga e l'alettone si accorcia di metà del rispettivo gioco. Se il vano sbocca su un bordo, non viene aggiunta una parete. Larghezze misurate dal bordo d'uscita. Inizio + lunghezza devono rientrare nell'apertura totale. Due STL separati, senza ponticelli. L'alettone viene appoggiato con la propria radice su Z=0; montaggio con cerniere dopo la stampa. Punta e sedi longheroni restano utilizzabili. L'eventuale porzione di ala sopra il vano viene mantenuta, anche a sbalzo.": 'Distance from root specifies the actual first end of the aileron; its minimum is half the root clearance (set clearance to zero to start at Z=0). End clearances are separate from position and hinge clearance. The aileron trailing edge remains aligned with the wing. Each nominal end clearance is split equally: the recess grows and the aileron shortens by half the clearance. No wall is added at an open edge. Widths are measured from the trailing edge. Start + length must fit within the total span. Wing and aileron export as separate STLs, without bridges. The aileron root rests on Z=0; hinges are fitted after printing. Wingtip and spar seats remain available. Wing material above the recess is retained, including any overhang.', 'Seconda famiglia con inclinazione opposta e protezioni agli incroci; verifica PrusaSlicer opzionale prima del salvataggio STL.': 'Second family with opposite inclination and protected intersections; optional PrusaSlicer verification before saving the STL.', 'Da 1 a 50 posizioni per nervatura, uniformi tra il 22% e il 74% della corda (una sola: 48%). Le posizioni incompatibili con bordi, sedi e scassi sono escluse. Percorso verificabile con PrusaSlicer abilitando la verifica opzionale.': 'From 1 to 50 positions per rib, uniformly spaced between 22% and 74% chord (one position: 48%). Positions conflicting with edges, seats or recesses are excluded. Enable the optional PrusaSlicer check to verify the path.', "Posizione: distanza dal bordo d'entrata in % della corda. Diametro: barra/tubo da inserire. Lunghezza Z: mm dalla radice; vuota = intera semiala. Imposta un numero maggiore di zero per abilitare i campi.": 'Position: distance from the leading edge as % chord. Diameter: rod/tube to insert. Z length: mm from root; blank = entire half-wing. Set a count greater than zero to enable the fields.', "Ruota le sezioni complete, comprese nervature, sedi e alettone. Le sedi fuori dal perno seguono lo svergolamento: valutarne l'accoppiamento con longheroni rigidi. Il raccordo centrale mantiene il profilo della radice.": 'Rotates complete sections, including ribs, seats and aileron. Seats away from the pivot follow the twist: check compatibility with rigid spars. The centre connector retains the root airfoil.', "Configura l'ala nei pannelli del wizard. Usa Avanti e Indietro per navigare.\nFile → Importa/Esporta legge e salva la configurazione completa in JSON.\nIl salvataggio della configurazione è distinto dall'esportazione STL.\nPrusaSlicer è opzionale: la verifica si attiva nel primo pannello.": 'Configure the wing in the wizard panels. Use Next and Back to navigate.\nFile → Import/Export loads and saves the complete JSON configuration.\nSaving a configuration is separate from exporting an STL.\nPrusaSlicer is optional; enable its verification in the first panel.'})

CATALOG.update({'Trapezoidale': 'Trapezoidal', 'Ellittica': 'Elliptical', 'Freccia linea centrale (mm)': 'Centreline sweep (mm)', 'Apri il pannello o aggiorna le anteprime per leggere la configurazione corrente.': 'Open the panel or update previews to read the current configuration.', 'In attesa di esportazione': 'Waiting for export', 'Pronto. Imposta i parametri e scegli il file STL.': 'Ready. Set the parameters and choose an STL file.', 'Senza nervature, i longheroni sono facoltativi.': 'Spars are optional when ribs are disabled.', 'Analisi travel, ritrazioni e crescita Z nel G-code…': 'Analysing G-code travel moves, retractions and increasing Z…', 'Bordo attacco': 'Leading edge', 'Bordo uscita': 'Trailing edge', 'Centro ellisse': 'Ellipse centre', 'Corda radice': 'Root chord', 'Esportazione e verifica STL del raccordo…': 'Exporting and checking connector STL…', 'Esportazione e verifica STL…': 'Exporting and checking STL…', 'G-code testuale': 'Text G-code', 'Preparazione del modello': 'Preparing model', 'Raccordo centrale': 'Centre connector', 'applicazione washout': 'applying washout', 'canali coassiali': 'coaxial channels', 'controllo mesh': 'mesh check', 'elaborazione del pezzo': 'processing piece', 'fessure delle nervature': 'rib slits', 'impostazioni e rapporti': 'settings and reports', 'nervature e setti': 'ribs and webs', 'punta ellittica': 'elliptical wingtip', 'radici inclinate': 'angled roots', 'ricalcolo separato': 'separate recalculation', 'scrittura STL': 'writing STL', 'separazione del vano': 'separating recess', 'solido nominale': 'nominal solid', 'verifica sezioni sulla mesh finale': 'checking final mesh sections', 'verifica vertici': 'checking vertices', 'verifica zero retrazioni': 'zero-retraction check', 'Lunghezza effettiva': 'Effective length', 'Da Z': 'From Z', 'Gioco lungo cerniera': 'Hinge clearance', 'Chiusure alle estremità': 'End caps', "Vista d'insieme dei componenti configurati": 'Overview of configured components', 'Vista in pianta': 'Plan view', 'Pianta': 'Planform', 'ellittica con terminale finito': 'elliptical with finite end', 'trapezio': 'trapezoidal', 'Nervature ala, punta e alettone': 'Wing, wingtip and aileron ribs', 'Esportazione con impostazioni Spiral Vase senza retrazioni.': 'Export with zero-retraction Spiral Vase settings.', 'Ogni corpo viene esportato separatamente.': 'Each body is exported separately.', 'Schema dei giochi, non in scala.': 'Clearance diagram, not to scale.', 'chiusure disattivate': 'end caps disabled', 'Nessun longherone': 'No spars'})

CATALOG.update({'Corda terminale ellisse (mm)': 'Ellipse end chord (mm)', 'coppie nella vista generale': 'pairs in the overview', 'pianta senza washout': 'planform without washout', 'coppie': 'pairs', 'rampe': 'ramps', 'sviluppo Z': 'Z extent', 'Larghezza accesso': 'Opening width', 'Lunghezza accesso': 'Opening length', 'Profondità per lato': 'Depth per side', 'Lunghezza lungo Z': 'Length along Z', 'Radice a sinistra, estremità a destra': 'Root at left, tip at right', 'radice a sinistra, punta a destra': 'root at left, tip at right', 'Base a Z ala': 'Base at wing Z', 'Base: piano di stampa': 'Base: print plane', 'Base: radice ala': 'Base: wing root', "Bordo d'uscita vincolato all'ala": 'Trailing edge aligned with the wing', 'Altezza asola': 'Slot height', 'Battuta per lato': 'Lip per side', 'Centro: radice': 'Centre: root', "bordo d'attacco": 'leading edge', "una sola coppia d'esempio": 'one example pair', 'Corpo X/Y/Z': 'Body X/Y/Z', 'gioco per lato': 'clearance per side', 'Estradosso → centro': 'Upper surface → centre', 'Profondità battuta': 'Lip depth', 'Gioco radice': 'Root clearance', 'Gioco punta': 'Tip clearance', 'Dettaglio accesso e battuta · vista locale apertura': 'Opening and lip detail · Local opening view', 'Dettaglio in pianta · ala e alettone reali': 'Plan-view detail · Actual wing and aileron outlines', 'Dettaglio reale in pianta · stessa scala sui due assi': 'Actual plan-view detail · Same scale on both axes', 'Diedro': 'Dihedral', 'per semiala': 'per half-wing', 'complessivi': 'total', 'Distacco uniforme': 'Uniform offset', 'linea effettiva': 'effective extrusion width', 'gioco aggiuntivo': 'extra clearance', 'Riserva femmina': 'Female allowance', 'Interasse effettivo': 'Actual spacing', 'Profondità totale al centro': 'Total depth at centre', 'Ellisse con corda terminale finita per la stampa. Le maniglie sui due bordi si spostano indipendentemente. Punta aggiuntiva disponibile.': 'Ellipse with finite end chord for printing. Leading and trailing edge handles move independently. An additional wingtip is available.', 'Estremi: lunghezza · lato cerniera: larghezze · centro: sposta.': 'Ends: length · Hinge side: widths · Centre: move.', 'senza washout': 'without washout', 'con washout': 'with washout', 'della corda terminale': 'of the tip chord', 'Cerniera in pianta': 'Plan-view hinge clearance', 'Generazione attiva': 'Generation enabled', 'Arancio: innesti · Viola: collegamenti doppi': 'Orange: sockets · Purple: double connections', 'Inizio washout a': 'Washout starts at', 'angolo finale a': 'final angle at', 'dalla radice': 'from the root', 'Ala orizzontale, radice a sinistra': 'Horizontal wing, root at left', 'Linea centrale': 'Centreline', "dal bordo d'attacco": 'from the leading edge', 'Calcolo: prolungamento della pianta ellittica.': 'Calculation: continuation of the elliptical planform.', 'Lunghezza aggiuntiva': 'Added length', 'Margine asola/bordo': 'Slot-to-edge margin', 'Metà apertura': 'Mid-span', 'impostata': 'specified', 'impostato': 'specified', "Offset verso l'intradosso": 'Offset towards lower surface', 'coperchio da realizzare a parte': 'cover to be made separately', 'Semiala': 'Half-wing', 'Corde': 'Chords', 'Sedi longheroni': 'Spar seats', 'Ugello': 'Nozzle', 'Strato': 'Layer', 'Servo tipo': 'Servo type', 'dal LE': 'from LE', 'Giochi': 'Clearances', 'Alleggerimenti ovali': 'Oval lightening holes', 'fino a': 'up to', 'per nervatura': 'per rib', 'vincolo zero retrazioni': 'zero-retraction constraint', 'Posizione di stampa (X/Z) · nervature schematiche': 'Print orientation (X/Z) · Schematic ribs', 'Quote in mm · scala uniforme in ciascuna vista · prima del washout': 'Dimensions in mm · Uniform scale within each view · Before washout', 'Quote reali in mm. Ai bordi aperti D/E sono margini; F include lo smusso in pianta a metà alettone.': 'Actual dimensions in mm. At open edges, D/E are margins; F includes the bevel in plan view at mid-aileron.', 'Distanza radice': 'Root distance', 'Radice a sinistra': 'Root at left', 'estremità a destra': 'tip at right', 'semiala': 'half-wing', 'corde': 'chords', 'Rosso: accesso · arancio: sede coperchio': 'Red: opening · Orange: cover seat', 'asse': 'axis', 'Sporgenza corpo stimata': 'Estimated body protrusion', 'Margine verso estradosso': 'Upper surface margin', 'Schema frontale di assemblaggio (Z/Y)': 'Assembly front view (Z/Y)', 'Sezione X/Y della stessa cerniera · profilo reale': 'X/Y section of the same hinge · Actual airfoil', 'Sezione alla radice': 'Root section', 'Sezione schematica · battuta e fondo dello scasso': 'Schematic section · Lip and recess bottom', 'Sezioni alla base, al 60% e al 90% della punta': 'Sections at the base, 60% and 90% of wingtip length', 'Sezioni della punta': 'Wingtip sections', 'Viola: asole · tratteggio: sviluppo degli inviti di sostegno.': 'Purple: slots · Dashed: support lead-in extent.', 'mm · E: intradosso → fondo al centro, lungo Y (prima del washout)': 'mm · E: lower surface → bottom at centre, along Y (before washout)'})

# Dynamic dimension legends and progress text retain their numbers and units.
_WORDS={'Passo':'Step','di':'of','Radice':'Root','Estremità':'Tip','Punta':'Wingtip','Ala':'Wing','Alettone':'Aileron','Raccordo':'Connector','centrale':'centre','corda':'chord','Freccia':'Sweep','Apertura':'Span','Lunghezza':'Length','Larghezza':'Width','Altezza':'Height','Profondità':'Depth','Spessore':'Thickness','Distanza':'Distance','Gioco':'Clearance','cerniera':'hinge','cerniere':'hinges','asole':'slots','nervature':'ribs','longheroni':'spars','sedi':'seats','scasso':'recess','battuta':'lip','chiusure':'end caps','specchiate':'mirrored','originali':'original','perno':'pivot','centro':'centre','quota':'coordinate','quote':'coordinates','bordo':'edge','attacco':'leading','uscita':'trailing','inizio':'start','fine':'end','attivo':'enabled','attiva':'enabled','attivi':'enabled','attivate':'enabled','disattivo':'disabled','disattiva':'disabled','disattivati':'disabled','disattivate':'disabled','sotto':'below','sopra':'above','inferiore':'lower','superiore':'upper','sinistra':'left','destra':'right','iniziale':'initial','finale':'final','nominale':'nominal','effettiva':'effective','effettivo':'effective','perimetro':'perimeter','stampa':'printing','stampabile':'printable','dettaglio':'detail','legenda':'legend','profilo':'airfoil','profili':'airfoils','superficie':'surface','supporti':'supports','supporto':'support','femmina':'female','maschio':'male','linguetta':'tongue','riserva':'allowance','distacco':'offset','uniforme':'uniform','linea':'line','aggiuntivo':'extra','provino':'test piece','configurazione':'configuration','esportazione':'export','importazione':'import','sezionatura':'sectioning','sezioni':'sections','taglio':'cut','tagli':'cuts','pezzo':'piece','pezzi':'pieces','fase':'stage','verifica':'check','controllo':'check','geometria':'geometry','salvata':'saved','caricata':'loaded','completata':'completed','non':'not','eseguita':'performed','errore':'error','generazione':'generation','anteprima':'preview','anteprime':'previews','rotazione':'rotation','angolo':'angle','lungo':'along','locale':'local','base':'base','dimensioni':'dimensions','nervatura':'rib','apertura':'span'}
_WORDS.update({'attive':'enabled','attivati':'enabled','estremi':'ends','intradosso':'lower surface','estradosso':'upper surface','corpo':'body','corde':'chords','schematica':'schematic','laterale':'side','rosso':'red','arancio':'orange','viola':'purple','inclinazione':'angle','riempimento':'infill','ritrazioni':'retractions','traslazione':'translation','nella':'in the','della':'of the','delle':'of the','dal':'from the','al':'at the','prima':'before'})
_WORD_RE=re.compile(r'(?<!\w)('+ '|'.join(sorted(map(re.escape,_WORDS),key=len,reverse=True))+r')(?!\w)',re.I)
_LOOKUP={k.casefold():v for k,v in _WORDS.items()}
_PHRASE_RE=re.compile('|'.join(sorted(map(re.escape,CATALOG),key=len,reverse=True)))

def translate(text,language):
    if language!='en' or not text:return text
    normalized=text.replace('’',"'")
    if normalized in CATALOG:return CATALOG[normalized]
    lines=[]
    for line in normalized.split('\n'):
        if re.match(r'^\s*(?:[A-Za-z]:[\\/]|[\\/]{2})',line):lines.append(line);continue
        # Replace exact phrases before individual legend words.
        line=_PHRASE_RE.sub(lambda m:CATALOG[m.group()],line)
        line=_WORD_RE.sub(lambda m:_LOOKUP[m.group().casefold()].capitalize() if m.group()[0].isupper() else _LOOKUP[m.group().casefold()],line)
        lines.append(line)
    return '\n'.join(lines)

_installed=False

def install_dialog_translations():
    global _installed
    if _installed:return
    _installed=True
    def wrap(original):
        @functools.wraps(original)
        def call(*args,**kwargs):
            root=kwargs.get('parent') or tk._default_root
            if root is not None and hasattr(root,'tr'):
                args=tuple(root.tr(a) if isinstance(a,str) and i<2 else a for i,a in enumerate(args))
                kwargs={k:root.tr(v) if k in ('title','message','detail') and isinstance(v,str) else v for k,v in kwargs.items()}
                if 'filetypes' in kwargs:kwargs['filetypes']=[(root.tr(a),b) for a,b in kwargs['filetypes']]
            return original(*args,**kwargs)
        return call
    for name in ('showinfo','showwarning','showerror','askquestion','askokcancel','askyesno','askyesnocancel','askretrycancel'):
        setattr(messagebox,name,wrap(getattr(messagebox,name)))
    for name in ('askopenfilename','asksaveasfilename','askdirectory'):
        setattr(filedialog,name,wrap(getattr(filedialog,name)))
