# pyRcWing

**pyRcWing** è un’applicazione desktop per configurare ali RC e componenti stampabili in 3D. Offre un wizard per geometria, profili NACA, washout, punta, longheroni, alettone, cerniere, servo, raccordo centrale e sezionatura in pezzi. Esporta i componenti in formato STL.

L’applicazione è sviluppata da **Marco Antinori**. Per informazioni e contatti: [marco.antinori@outlook.it](mailto:marco.antinori@outlook.it).

## Stato del progetto

Questa pubblicazione contiene la versione **9.1**. La modalità Spiral Vase a fessure e i percorsi di stampa senza retrazioni sono sperimentali. Prima di stampare un componente completo, controlla ogni STL e l’anteprima dello slicer; stampa prima un provino e verifica il G-code, in particolare che non siano state introdotte retrazioni indesiderate.

## Requisiti

- Windows 10 o successivo
- Python 3.11 con Python Launcher (`py`)
- Connessione Internet al primo avvio, per installare le librerie Python mancanti

Il launcher installa `cadquery` e `shapely` nell’ambiente utente di Python 3.11, se non sono già disponibili. Non crea né richiede un ambiente virtuale. Le dipendenze sono distribuite secondo le rispettive licenze.

## Avvio rapido

1. Scarica o clona il repository in una cartella locale.
2. Installa Python 3.11 per Windows includendo Python Launcher e Tcl/Tk.
3. Fai doppio clic su `Avvia_pyRcWing.cmd`.
4. Al primo avvio, attendi il completamento dell’installazione automatica delle dipendenze.

In alternativa, da un terminale aperto nella cartella del progetto:

```bat
Avvia_pyRcWing.cmd
```

Per installare manualmente le dipendenze:

```bat
py -3.11 -m pip install --user cadquery shapely==2.2.0
py -3.11 pyRcWing.py
```

## Configurazioni ed esportazioni

Le configurazioni dell’ala possono essere importate ed esportate dall’applicazione in formato JSON. Gli STL e i file di verifica vengono creati nella cartella scelta durante l’esportazione. Non pubblicare configurazioni, STL o dati personali senza aver prima controllato il loro contenuto.

PrusaSlicer è opzionale: la verifica G-code si può attivare dalle impostazioni dell’applicazione. I controlli geometrici e della mesh vengono comunque eseguiti dall’app.

## Contribuire

Contributi, segnalazioni di problemi e proposte sono benvenuti. Puoi aprire una Issue o una Pull Request su GitHub. Descrivi le modifiche e, per cambiamenti geometrici o di esportazione, allega una configurazione di esempio e i risultati verificabili.

Inviando intenzionalmente un contributo per l’inclusione nel progetto, dichiari di avere il diritto di inviarlo e accetti i termini della licenza `LICENSE` per quel contributo.

## Licenza e attribuzione

Il progetto è distribuito secondo la licenza personalizzata con obbligo di attribuzione inclusa nel file [`LICENSE`](LICENSE). È consentito usare, modificare e ridistribuire il progetto nel rispetto delle condizioni indicate. Le versioni derivate distribuite al pubblico devono conservare il credito:

> Originally created by Marco Antinori

Le versioni modificate devono essere identificate come tali e non devono suggerire l’approvazione dell’autore originale. Questa licenza personalizzata non è una licenza Open Source approvata da OSI. Le dipendenze di terzi restano soggette alle proprie licenze.

---

# pyRcWing (English)

**pyRcWing** is a desktop application for configuring RC wings and 3D-printable components. Its wizard covers planform geometry, NACA airfoils, washout, wing tips, spars, ailerons, hinges, servo pockets, center sections and cutting components into printable pieces. It exports components as STL files.

The application is developed by **Marco Antinori**. Contact: [marco.antinori@outlook.it](mailto:marco.antinori@outlook.it).

## Project status

This public release contains **version 9.1**. Slotted Spiral Vase and zero-retraction printing paths are experimental. Inspect every STL and the slicer preview before printing; print a test piece first and review the G-code, especially to check that unwanted retractions have not been introduced.

## Requirements

- Windows 10 or later
- Python 3.11 with the Python Launcher (`py`)
- Internet access on first launch to install missing Python packages

The launcher installs `cadquery` and `shapely` into the Python 3.11 user environment if they are not already available. It does not create or require a virtual environment. Dependencies are distributed under their respective licenses.

## Quick start

1. Download or clone this repository to a local folder.
2. Install Python 3.11 for Windows, including Python Launcher and Tcl/Tk.
3. Double-click `Avvia_pyRcWing.cmd`.
4. On first launch, wait for the automatic dependency installation to finish.

Alternatively, run this from a terminal opened in the project folder:

```bat
Avvia_pyRcWing.cmd
```

To install dependencies manually:

```bat
py -3.11 -m pip install --user cadquery shapely==2.2.0
py -3.11 pyRcWing.py
```

## Configurations and exports

Wing configurations can be imported and exported as JSON from the application. STL files and verification reports are written to the folder selected during export. Review configuration files, STL files and personal information before publishing them.

PrusaSlicer is optional; G-code verification can be enabled in the application. The application still performs its geometry and mesh checks when slicer verification is disabled.

## Contributing

Bug reports, suggestions and code contributions are welcome. Open a GitHub Issue or Pull Request. For geometry or export changes, include an example configuration and verifiable results where possible.

By intentionally submitting a contribution for inclusion in the project, you confirm that you have the right to submit it and agree that the contribution is covered by the terms in `LICENSE`.

## License and attribution

This project is distributed under the custom attribution license in [`LICENSE`](LICENSE). You may use, modify and redistribute the project subject to its terms. Publicly distributed derivative versions must retain this credit:

> Originally created by Marco Antinori

Modified versions must be identified as modified and must not imply endorsement by the original author. This custom license is not an OSI-approved Open Source License. Third-party dependencies remain subject to their own licenses.
