# Radar de Licitaciones

**English** · [Español](README.es.md)

Finds Spanish public-sector tenders for **security awareness, training, phishing
simulation and email security**, plus **wider cybersecurity** (SOC, information security,
compliance with Spain's ENS security framework), and puts them in an inbox to work
through. Built for teams selling these services to Spanish public bodies, it also shows
which contracts are about to expire and who is winning the work. It runs locally on a Mac
with only the Python standard library, drawing on PLACSP (Spain's public procurement
platform), the EU's TED journal and Catalonia's own platform.

> **About the language.** The interface, the search profiles and everything you read on
> screen are in Spanish, as are the code and its comments. This README quotes on-screen
> labels in Spanish, with an English gloss on first use, so they can be matched to the
> app. Code blocks are kept exactly as they are in the Spanish version.

It does not connect to any CRM or to anyone's notes. Everything lives in this folder,
so you can copy it, AirDrop it to a colleague or push it to a repository, and it works
the same on any Mac.

---

## Up and running in 30 seconds

Double-click **`Radar de Licitaciones.app`**.

It opens like any other Mac program: its own window, its own Dock icon, its own menu.
Behind the scenes it starts the Python server, waits for it to respond and, before
showing the inbox, does two things in a row:

1. **Installs the new version of the program, if there is one.** It asks GitHub for the
   latest release and, if it is newer than yours, downloads it, installs it and the
   application reopens by itself. It takes a few seconds. See
   [Updating the program](#updating-the-program).
2. **Fetches everything published since last time.** Meanwhile you see real progress
   — which source, how many megabytes, how long it has been running — and the list
   appears already up to date. It usually takes about a minute.

**If it has just updated, it tells you.** When it reopens on the new version, the
start-up screen shows «Actualizado a la versión X» (Updated to version X) and **what has
changed since the version you had** — the notes for every version you skipped — while the
search carries on underneath. When both tasks finish it does not close by itself: it
says «Todo listo» (All done) and waits for you to press **Continuar** (Continue). See
[Updating the program](#updating-the-program).

There is no terminal to keep open, and quitting with ⌘Q stops the server with it.

**Neither step can be skipped.** There is no "show me the inbox without waiting" button
and no time limit: as long as whatever it is waiting for shows signs of life — bytes
arriving, a phase changing, a retry — it waits. The only way out is for when something
has hung: after **three minutes with no sign of life**, «Entrar sin esperar» (Go in
without waiting) appears, and it tries again the next time you open the application.
Three minutes, and no less, because PLACSP can stay silent for up to two on each
connection attempt, and that is slowness, not a hang.

There are two cases where it does not wait, and neither of them is skipping anything:

- **If it searched less than ten minutes ago, the search is not repeated.** It has
  already been done; closing the window and opening it again does not cost another
  minute. The version, on the other hand, is always checked: it is a single request to
  GitHub.
- **The initial load is not waited for there.** That takes hours, so the app goes
  straight in and the bar in the header keeps track of it — the one that says «puedes
  trabajar mientras» (you can keep working meanwhile). Nor is a new version installed
  while it runs (swapping the code out from under a load that takes hours is asking for
  trouble); it will be installed the next time you open the app.

The **«Buscar ahora»** (Search now) button is no longer in the header: with all this,
you never need to press it. It is still there, at the bottom of **Términos de búsqueda**
(Search terms), which is where you want it — after changing the words, to see what they
bring in — and **underneath it reports the same** as the start-up screen: which source,
how many megabytes and how long it has been running.

**The app carries the program inside it** — `radar/`, `web/` and the certificates go in
`Contents/Resources` — so it is **a single 1.7 MB file** that you can drag to
Applications, zip and send by email. All the other Mac needs is Python 3.9 or later.

If it is not there, it builds in a second:

```bash
python3 herramientas/construir_app.py
```

**`start.command`** is still there and does the same without its own window: it
downloads what is new and opens the inbox in the browser. It is the original route, and
the one to use if something seems off, because it reports what it is doing in the
terminal.

> **The first time, macOS is suspicious.** The app is not signed with an Apple
> certificate — that costs $99 a year and is not worth it for an in-house tool — so
> if you downloaded it from GitHub the system will refuse to open it with a double-click.
> You fix this once: **right-click the app → Open**, and confirm. From then on it opens
> normally. If you prefer the terminal:
>
> ```bash
> xattr -dr com.apple.quarantine "Radar de Licitaciones.app"
> ```
>
> And if you build it yourself with the command above, none of this happens.

The first run is different and gets its own section, just below.

While it downloads, the terminal shows a line that keeps updating with the source, the
page, the megabytes received so far and the elapsed time:

```
⠹ etapa 3/4 · placsp:agregadas · el histórico de 2025 (año 2 de 3) · descargando 84,2 MB/133,0 MB (63%) a 1,4 MB/s · 2.950 fichas · 1m 12s
```

If that line is moving, it is working. PLACSP is slow to respond at times and each
attempt waits up to two minutes before retrying, so a long stretch on "conectando"
(connecting) is normal and there is no need to close anything.

And if a download is cut off halfway, it retries up to four times with increasing waits
instead of giving up at the first failure, which is what used to leave a whole year
marked as failed because of a single timeout. What it **cannot** do is resume: tested
against the platform, PLACSP ignores the `Range` header and sends the whole file again,
so a break in the central government platform's ZIP means repeating that download. The
program asks for the rest of the file anyway, and would use what has already been
downloaded the day the platform allows it; in the meantime it makes sure of what
matters, which is never stitching together two halves of different files.

If you prefer the terminal:

```bash
python3 radar.py ingest && python3 radar.py serve
```

Requirements: **Python 3.9 or later**. Note that macOS no longer ships with it: Apple
removed it from the system in Catalina, so on a brand-new Mac you have to install it once
from [python.org](https://www.python.org/downloads/macos) — `start.command` detects this
and explains it. Apart from that there is nothing else to install: no libraries, no
database, no accounts.

---

### Passing it on to a colleague

One file and one warning.

```bash
python3 herramientas/construir_app.py --zip
```

This produces a **"Radar de Licitaciones X.Y.Z.zip" of about 1,000 KB**. That is all
you need to send: by email, Slack or AirDrop. Your colleague unzips it, drags the app to
Applications and opens it. No folders to copy, no paths to respect, nothing to install
beyond Python.

The warning: **that copy carries the generic search-term template, not yours.** That is
deliberate — terms refined over months do not travel inside a package that gets handed
round — but it means it would start with a filter that finds nothing. If you want it to
start with your configuration, send your `config/perfiles.json` separately and have them
put it in:

```
~/Library/Application Support/Radar de Licitaciones/config/perfiles.json
```

What **never** travels inside the app, and it is worth knowing: your database, your
triage and your notes. A test guards this (`tests/test_rutas.py`), because sending
someone the app must not mean accidentally sending them the opportunities you are working
on.

And the first time, macOS will distrust the app like any unsigned program downloaded
from the internet: right-click → Open. It is explained above.

### Where your data lives

It depends on how you use it, and the rule is explicit:

| | |
|---|---|
| App built **inside the project folder** | the project's `data/` and `config/`, as always |
| App **in Applications** or received from someone | `~/Library/Application Support/Radar de Licitaciones` |
| `RADAR_DATOS` in the environment | wherever that variable says, and it overrides the other two |

In other words: **if you work from the repository, nothing changes and your database
stays where it is.** The app you build there uses that code and that database. If you
drag the app to Applications it becomes a separate installation and would start from
scratch, with its own empty database; if you want to take the one you already have with
you, move it once:

```bash
mkdir -p ~/Library/Application\ Support/Radar\ de\ Licitaciones
mv data ~/Library/Application\ Support/Radar\ de\ Licitaciones/
mkdir -p ~/Library/Application\ Support/Radar\ de\ Licitaciones/config
mv config/perfiles.json ~/Library/Application\ Support/Radar\ de\ Licitaciones/config/
```

Nothing is ever written inside the app. This is not a preference: a `.app` may sit in
`/Applications`, which is not yours; it is signed, and writing inside it invalidates the
signature; and an update replaces it entirely, so anything saved there would be lost in
the next version.

## The first run

A newly created database does not fill itself, and this is what you need to know so you
don't think the tool is broken.

The reason is the way PLACSP publishes: there is no query that returns "everything from
the last two years". There is a **daily feed** that chains snapshots backwards, and
**annual ZIPs** with the historical archive. Each morning's ingestion only needs the
first page of the feed, so that is what it asks for when it doesn't know where it left
off; and as soon as it records where it has got to, it never looks further back again.
With a plain `ingest` you would be left with about **50 matches** and no way of
recovering the rest.

That is why, when the database is empty, neither the app nor `start.command` runs a
normal search: they build the history in four stages, from cheapest to most expensive:

| | what it fetches | what it costs |
|---|---|---|
| 1 | European (TED) and Catalan notices | a few minutes, barely any disk space |
| 2 | history of the aggregated platforms and preliminary market consultations | ~360 MB + ~4 min of processing |
| 3 | history of the central government platform | ~5 GB + ~15 min of processing |
| 4 | everything published since the ZIPs' cut-off date | a few minutes |

Download times are not listed because they cannot be promised: they depend on your
connection and on what PLACSP delivers that day. Measured here, those 5 GB have taken
anything from a few minutes to almost two hours. What is predictable is the processing
— opening the ZIPs and loading the million-plus records into the database — because it
only depends on your machine.

**The application opens as soon as stage 1 finishes**, already with about a thousand
matching procurement files (*expedientes*: one procurement procedure, which can produce
several notices over its life). In the app, the start-up screen explains it meanwhile —
«Primera vez: preparando tu radar», with what the stage fetches and what it costs —,
welcomes you with the notes of the version you start on and, when it finishes, shows a
summary of what has arrived and **Continuar**. The other stages keep downloading in the
background while you work: a notice at the top shows the stage, the megabytes arriving
and a progress bar, and the counters in the header go up by themselves without reloading
the page.

**If it is interrupted, it resumes by itself.** The load records in the database which
stages are still missing (`etapas_pendientes` in `preferencias`): the requested ones when
it starts, and each one is removed when it finishes without errors. If you close the app
halfway, the network drops or a source fails, the next time you open it the missing
stages run in the background instead of the usual start-up search. A database that
already had history before this record has nothing recorded, and nothing is asked of it.

Stages 2 and 3 are the ones that fill **Vencimientos** (Expiring contracts) and
**Adjudicatarios** (Winning bidders), which need award history. And stage 3 is the one
that brings in the ten autonomous communities (Spain's regions) that do not have their
own platform (Valencia, Castilla y León, Aragón, Murcia…).

While the initial load is running, the start-up search, «Buscar ahora» and the morning
task wait their turn: two ingestions at once fight over SQLite's write lock. This is
normal, and in **Términos de búsqueda** the button says so — it appears disabled,
showing the stage — with a line underneath describing what it is doing.

From the terminal, if you want to control it yourself:

```bash
python3 radar.py ingest --primera-carga              # las cuatro etapas seguidas
python3 radar.py ingest --primera-carga --etapas 1   # solo la rápida
python3 radar.py ingest --primera-carga --etapas 2 3 4
```

---

## How to use it

The views live in the **sidebar**, as in Zepo Desk: Bandeja (Inbox), Resumen (Summary)
and Otras licitaciones (Other tenders) at the top; Vencimientos (Expiring contracts),
Adjudicatarios (Winning bidders) and Analítica (Analytics) under «Mercado» (Market); and
Términos de búsqueda (Search terms) at the bottom, next to the radar's status (last search,
how the sources are doing and the version). **⌘1…⌘7** switch views in that same order.

Clicking a tender **opens its record on the right** and the list narrows to make room,
with the row highlighted; in a narrow window the record floats on top. Escape closes it.
The app follows macOS light or dark mode.

### On opening: the search and the summary

Every time it opens, the app installs the new version if there is one and fetches what
has been published since last time. When it finishes it **does not go straight in**: it
shows a summary and waits for you to press **Continuar** (Continue).

- **How many new tenders** the search brought in, per profile, and below that the IT
  themes of «Otras licitaciones» (Cybersecurity, Cloud…). It counts case files, not
  notices: a TED notice that joins a case file you already had is not a new tender.
- **The version**, and whether it is the latest one published on GitHub.
- If a source failed or was cut off, it says so too.

**If the search is slow.** The State Procurement Platform sometimes answers very slowly
—0.05 MB/s has been seen, with pages of about 13 MB—, and then an ordinary search can run
for over an hour without being stuck. After two minutes the screen explains why it is
taking so long (speed, retries, how many days have to be caught up) and offers **«Entrar
sin esperar»** (Go in without waiting). Waiting is better, because the summary comes at
the end; but if you go in, the search carries on in the background, the header keeps
reporting it and, when it finishes, says **«Búsqueda terminada: N nuevas · Ver
resumen»**.

**If it really gets stuck.** A watchdog checks that the search keeps moving: bytes,
records, pages or retries. If **15 minutes go by with nothing moving**, it cuts that
source, keeps what had already arrived and carries on with the rest; the next search
picks up the one that was cut. Slow is not stuck: as long as data keeps arriving, nothing
is cut.

### Resumen (Summary)

The same as on opening, for any period:

| Period | What it counts |
|---|---|
| Última búsqueda (last search) | what the last finished search brought in |
| Desde la última vez (since last time) | what has come in since you previously opened the app |
| Última semana · Último mes · Último trimestre (week · month · quarter) | what was **published** in that span, by the date of the case file's first notice |

The first two count what entered the radar; the calendar ones, what was published, so
that after the initial load «last quarter» is not three years of history. The case files
are listed below, with the same card as the Inbox.

### The numbers in the Inbox

Every figure is a button: clicking it makes the list show exactly those tenders. They
all count **procurement files**, not notices, just like the list.

| Counter | What it is |
|---|---|
| abiertas (open) | passed the filter, still live and the deadline has not passed |
| cierran ≤7d (closing ≤7d) | of those, the ones that close this week |
| sin revisar (not reviewed) | you have marked them neither Seguir (Follow) nor Descartar (Discard) |
| siguiendo (following) | the ones you have marked to work on |
| coincidencias (matches) | everything that passed the filter, regardless of deadline or triage |

Under the list it says «110 de 2.716 coincidencias» (110 of 2,716 matches) and which
filters are applied, because the triage drop-down and the **«Solo abiertas» (Open only)
checkbox combine**: choosing «todo menos descartadas» (everything except discarded)
without unticking the box still shows only the open ones.

### Bandeja (Inbox)

Whatever has passed the filter, with **the days left to submit** in large type on the
right and, underneath in small type, how long ago it was published — which explains its
place in the list, now that the inbox opens sorted by most recently published. For each
tender you see the contracting authority, the value, the deadline and links to the
official tender documents.

The row of pills shows **both dates together**: «publicada 17 sept 2026» (published
17 Sept 2026) and «cierra 02 oct 2026» (closes 02 Oct 2026). The one at the top right
gives the age («hace 5 días», 5 days ago), which is for sorting at a glance; this one
gives the date, which is what people ask about when looking at the list and what gets
copied into an email. It is the date of the **first** notice in the procurement file,
the same one used to decide the «Nueva» (New) label, so the two can never contradict
each other.

**Whatever you mark as «siguiendo» (following) or «presentada» (submitted) never leaves
the inbox**, even if no profile matches it any more. That is deliberate: marking
something is your decision and outweighs the automatic filter. The record appears
without a profile pill, and its «Por qué ha entrado» (Why it's here) section says that
it is in the database but does not match any active profile, which is the truth.

We learnt this the hard way. When the profiles were narrowed, a €6.25 million contract
from Canal de Isabel II that was being followed, with 23 days left to bid, dropped out of
the inbox: its triage and notes were still in the database, intact, but there was no way
of seeing it — neither the status filter nor the free-text search reaches beyond the
matches — and the header counter said 1 where there were 2. Adjusting the terms must
not hide something you are working on.

**Discarded** items that stop matching do disappear, and that is deliberate too: there,
the filter and your decision say the same thing.

Tenders published less than a week ago carry the **Nueva** (New) label, the only
solid-filled one in the row, so it stands out without having to read it. The week is
counted from the **first** publication of the procurement file, not from the notice
being shown: if yesterday's award notice flagged a June tender as new, the label would
send someone to a contract that has already closed. Measured on the real database, that
naive rule flagged 16, and five of them were false.

**The profile drop-down lists the active ones**, even if one has not matched anything
yet: it appears with "(0)" next to it. It is the only way to see that activating a
profile has worked; if only those with records appeared, the one you have just switched
on would still be missing and it would look as if it had not been saved.

The sort drop-down offers **cierran antes** (closing soonest), **mejor encaje** (best
match), **publicación más reciente** (most recently published), **publicación más
antigua** (oldest published) and **mayor importe** (highest value). The two date options
also use the first publication of the procurement file, so sorting by "most recent" puts
the ones labelled Nueva right at the top.

Clicking a tender opens the detail panel, which holds the important part:
**«Por qué ha entrado»** (Why it's here), which says exactly which word or which CPV code
(the EU's Common Procurement Vocabulary) made it appear. If something should not be
there, this tells you what to fine-tune.

Each tender can be marked **Seguir** (Follow), **Presentada** (Submitted) or
**Descartar** (Discard), and you can add notes. When you discard, it asks for the reason
(outside the niche, value too low, incumbent locked in…); those reasons add up and let
you adjust the profiles with data rather than by eye. Triage is kept even if the tender
changes status or you change the profiles.

A single procurement file generates several notices over its life (tender, correction,
award by lot). The inbox groups them into a single row, marks it with an «N anuncios»
(N notices) label and shows the most advanced status.

Triage belongs to the **procurement file**, not the notice: whatever you mark applies to
all the notices in the group, and those published later inherit the decision. That is
what makes **discarding stick through later downloads**. Be clear about what that means:
discarding does not stop the tender from being downloaded — that way you can see whether
it ends up awarded, and to whom — what it does is take it out of the inbox, the expiring
contracts and the list of new items.

That includes the TED notice: everything above the EU threshold is published twice, and
the two rows are merged even though they share neither file number nor language — TED
numbers each notice separately and translates the title into Spanish — by pairing them
on exact value and closing date. When that pairing is ambiguous (two different tenders
with the same round value and the same closing date; 10 such cases were measured out of
629) **nothing is merged**: better two separate rows than mixing up the triage of two
procurement files.

When new tenders have come in since your last visit, a green **«N nuevas»** (N new) tab
appears so you can see just those.

### Otras licitaciones (Other tenders)

Everything the radar downloads that does **not** match your profiles. The radar pulls in
the whole of PLACSP — about 700,000 records including the history — and the profiles
keep a few hundred; the rest of the IT market was sitting in the database with no way of
seeing it. Here you can see it, organised by **topic**, chosen with multi-select chips
(none selected means "all"). The quoted terms are matched in Spanish, as written in the
tenders:

| Topic | How it is recognised |
|---|---|
| Ciberseguridad (Cybersecurity) | security software and antivirus (CPV 4873, 4876) or «ciberseguridad», «seguridad de la información», ENS, SOC, SIEM, pentest… |
| Cloud y hosting (Cloud and hosting) | web hosting and SaaS (72415, 72416, 72317) or «en la nube», «cloud», «SaaS», «hosting», Azure, M365… |
| IA y datos (AI and data) | text only (there is no CPV code for AI): «inteligencia artificial», «big data», «business intelligence», «chatbot», «RPA»… |
| Desarrollo y software (Development and software) | programming and development (7221, 7223, 7224, 7226, 72413) or «software», «aplicación web», «mantenimiento evolutivo»… |
| Licencias de software (Software licences) | the whole of division 48 or «licencias de software», «licencias Microsoft/Oracle/VMware»… |
| Infraestructura y hardware (Infrastructure and hardware) | computer equipment (302), servers (4882), their maintenance (5031, 5032) or «servidores», «CPD», «virtualización»… |
| Redes y telecomunicaciones (Networks and telecoms) | 322, 324, 3252, 3255, 642, 727, 5033, 45314 or «telefonía móvil», «fibra óptica», «wifi», «cableado estructurado»… |
| Consultoría y soporte IT (IT consultancy and support) | 721, 7222, 7225, 723, 725, 726, 728, 729 and plain 72000000, or «soporte informático», «CAU», «service desk»… |
| Resto de licitaciones (All other tenders) | everything that falls into none of the above: construction works, cleaning, supplies… |

A tender can be in several at once. Terms are matched as in the profiles — word stems,
including Catalan, Galician and Basque — and **without the name of the contracting
authority**, so that everything procured by the Instituto Nacional de Ciberseguridad
(INCIBE, Spain's National Cybersecurity Institute) does not count as cybersecurity just
because of its name. Several terms were dropped after measuring them against the real
database: plain «cortafuegos» (firewall) mostly turns out to be firebreaks on hillsides,
«portátiles» (portable/laptops) fire extinguishers and «cuadro de mando» (dashboard) the
control cabinet for street lighting.

It has its own search box and filters — region, contract type, value, sort order — and
opens showing **only what is open**: with closed ones included there are hundreds of
thousands. Each chip shows its count with the other filters applied; with closed ones
included and no search, the count is not calculated, because it would take eight
seconds.

**Whatever is already in the Bandeja does not appear here**, not even through another
notice from the same procurement file. And triage works just as it does in the Bandeja:
**«Seguir» moves it to the Bandeja** — which is what it does with any record you follow,
whether it matches or not — and «Descartar» removes it from the list (you can get those
back with «Ver descartadas», Show discarded).

Topics are calculated in the same pass as the profiles, so new items are classified
automatically. The first time after updating to this version, the start-up search takes
about a minute longer: it classifies the whole database. The rules live in
`radar/categorias.py` and belong to the program, not to each user: if they change in a
new version, the database is reclassified automatically.

### Vencimientos (Expiring contracts)

Contracts **already awarded** whose term ends soon, with the incumbent and the value.
The window buttons (3, 6, 12, 24 months) show how many expire in each period and for how
much, so you can compare at a glance. This is the list to call *before* the tender
documents come out, while you can still influence them. Only contracts that publish an
end date or a duration appear: if the source does not give one, the tender is left out
rather than estimated by eye.

### Adjudicatarios (Winning bidders)

Who is winning these contracts, grouping the variants of each company's registered name
(«S2 GRUPO …, S.L.U.» and «S2 Grupo … S.L.» are the same company). Clicking a company
expands its contracts.

By default it looks at what matches your profiles. The drop-down at the top changes the
**scope**: a specific profile, or a whole market topic — cybersecurity, cloud, all of
IT… — whether or not it matches your profiles. It is the same selector as in Analítica.

### Analítica (Analytics)

The questions that are not "what is out there today". Fifteen blocks, each led by a
sales question, in the order they are read:

| Block | Answers |
|---|---|
| Cuándo sale el trabajo (When the work comes out) | which months you need to be ready for. December publishes twice as much as August, and that gets planned in September |
| Tamaño de los contratos (Contract size) | how big these deals really are |
| Importe al que se están cerrando los contratos (Value contracts are being awarded at) | how far below budget they are being awarded |
| Cuánto tiempo tengo para presentar (How long I have to bid) | how many days there are from notice to deadline: if I see it today, whether there is time to write the bid |
| Top comunidades por adjudicaciones (Top regions by awards) | where the money already awarded has gone |
| Top comunidades por número total de adjudicaciones (Top regions by total number of awards) | where the most deals close, whatever their size |
| Top comunidades por licitaciones activas (Top regions by active tenders) | where there is money still in play, with the deadline still open |
| Top comunidades por número de licitaciones activas (Top regions by number of active tenders) | where the most tenders are open right now |
| Quién compra (Who buys) | which contracting authorities keep coming back, and which are worth going to see |
| Quién gana (Who wins) | which companies win the most procurement files, and who you will be competing against |
| Qué compran exactamente (What exactly they buy) | which CPV codes your product falls under, with a link to fine-tune the terms |
| Cómo se compra (How they buy) | the way in: open, simplified, restricted or by-invitation procedure |
| Cuándo entra en el forecast (When it hits the forecast) | how many days pass from publication to award |
| A quién llamo antes del pliego (Who to call before the tender) | how many contracts end within six months, with a known incumbent |
| Qué tengo de verdad hoy (What I really have today) | whether this is a pipeline or a historical archive |

It is filtered by **scope** and by one of three ranges (this year, last 24 months,
everything since 2024). The two blocks that talk about *now* — renewals and pipeline —
deliberately ignore the range and say so, because a filter that is silently ignored is
worse than one that is missing.

The scope can be your profiles — all of them or one — or one of the **market topics**
from «Otras licitaciones», or all of IT together. With a topic, it looks at the whole
market, whether it matches your profiles or not, and every block is recalculated over it:
calendar, values, regions, who buys, who wins… Two things change: there is no
**pipeline**, because the pipeline is your triage and your scores, and the CPV block does
not show "your product's codes". «Resto de licitaciones» is not offered: that is 600,000
records of construction and cleaning, and analysing them would take a long time to tell
you nothing about the IT market.

The first time a topic is viewed it takes a few seconds, up to five or ten for the
biggest, «Toda la IT» (All IT); after that it stays cached until something new enters
the database.

The four regional blocks come in pairs, money on the left and count on the right,
because **the two rankings almost never match, and that is where the information is**:
Catalonia is 3rd by euros and **2nd by number of deals**, the Basque Country 10th and
6th. A market of many small contracts and one of a few large contracts are worked
differently.

Three things to keep in mind when reading the regional breakdown:

- **The region is that of the contracting authority, not where the work is done.** The
  central government's centralised purchasing bodies are in Madrid, so Madrid absorbs
  national purchasing: measured, 67% of its awarded money comes from four central
  government bodies — Racionalización y Centralización (26%), Adquisiciones de Armamento
  (19.5%), Administración Digital (12.9%) and Infraestructura del MDE (8.3%), i.e.
  central purchasing, defence procurement, digital government and defence
  infrastructure — while the Comunidad de Madrid's own bodies do not reach 7%. "Madrid"
  here is not the Madrid market, and comparing it with regional GDP is comparing
  different things.
- **A procurement file's value adds up its lots rather than taking the largest.**
  Catalonia publishes one row per lot and PLACSP one per tender; with a plain maximum,
  the largest lot was counted and the rest thrown away. It is the only region that was
  affected: €51.9 million against the real €61.7 million, 19% too low, which made it
  drop from third place to fourth.
- **The count charts do not apply the €50 million cut-off.** A count is not skewed by one
  large contract, and setting it aside would hide tenders you can actually bid for. That
  is why a region can show more procurement files in the count chart than next to its
  money bar, and each chart's footnote says so.

And there are three things this tab does **not** do, all for the same reason:

- **It gives no total money figures, except in the regional breakdown.** The key that
  groups the notices of a single procurement file does not work across sources, so 126
  procurement files are duplicated between PLACSP and TED and carry almost €1 billion of
  thin air: the other blocks only show medians, bands and counts. The regional breakdown
  is the exception, and not for convenience: TED does not publish a region, so in each
  duplicated pair its copy falls under «sin comunidad» (no region) and not into anyone's
  total. It is the only cut of this database that can be summed without counting the
  same thing twice, and a test guards it.
- **And even there it sets the macro-contracts aside, but shows them.** A €2,646 million
  dynamic purchasing system is not a contract you can bid for, and on the same scale it
  leaves seventeen regions drawn as a one-pixel line. Those above €50 million are taken
  out of the bars and listed in the footnote with their name, their value and their
  region's true total. Among what is live they account for 96% of the money, and that is
  exactly the point: today there is no spread-out market, there are four purchasing
  platforms.
- **It gives no average values.** The mean is €4 million and the median €169,000: five
  contracts make up half the total. Those five appear by name and contracting authority,
  and you can see that three of them are the same framework agreement repeated.
- **It does not hide what it discards.** For the award discount (how far below budget a
  contract is awarded), half the sample is unusable — the source repeated the budget
  instead of the price, or compares one lot against the total of the whole framework —
  and that is shown on screen with its count, not tucked away in an asterisk.

Each block also has a minimum below which it is not drawn: a median of twelve cases
presented as a median is worse than a gap.

And in any view, **Exportar CSV** (Export CSV) downloads what you are looking at with
the filters applied, ready for Excel.

### Commands

```bash
python3 radar.py ingest                       # descarga las novedades
python3 radar.py ingest --primera-carga       # instalación nueva: trae el histórico
python3 radar.py ingest --backfill 2024,2025  # trae el histórico de esos años
python3 radar.py match                        # reevalúa los perfiles sin descargar
python3 radar.py clasificar                   # reclasifica todo por temática (un minuto)
python3 radar.py serve                        # abre la aplicación
python3 radar.py vencimientos --meses 6       # contratos que vencen pronto
python3 radar.py adjudicatarios               # quién gana estos contratos
python3 radar.py export salida.csv            # exporta a CSV
python3 radar.py programar                    # descarga automática cada mañana
python3 radar.py estado                       # cifras y salud de las fuentes
python3 radar.py doctor                       # ¿está todo en su sitio?
python3 radar.py actualizar --solo-comprobar  # ¿hay una versión nueva del programa?
python3 radar.py actualizar                   # la instala
```

`ingest` only re-evaluates the profiles against what it has just fetched, which is what
makes the morning download finish in seconds instead of going through all 673,755
records in the database. If you change the search terms, it detects this and goes
through everything anyway; and `match` always looks at everything — that is what it is
for.

### Updating the program

The application does it by itself, every time it opens, and there is no button to do it
or to put it off: an update that can be postponed gets postponed for ever. The start-up
screen asks GitHub for the **latest published release**; if it is newer than yours, it
downloads it, installs it and the application restarts with it on its own, before it
starts searching for tenders. From the terminal you can do the same with the two commands
above.

**It does not touch `data/`**, where your database, triage and notes are, **nor
`config/perfiles.json`**, which holds your search terms. If a download is in progress,
it waits for it to finish — or, if it is the initial load, leaves it for next time. Any
database changes the new version brings are applied automatically on start-up.

When it reopens on the new version, the start-up screen confirms it and shows **what is
new since the version you had**, which is the GitHub release notes for each intermediate
version (up to six; the rest are linked). You read them while the tender search carries
on, and once both are done the screen waits for **Continuar**. If you close it before
pressing it, you will see them again next time. Without an update in between, start-up is
as usual and the screen goes away by itself. On a fresh install, with no version
recorded, the screen welcomes you and shows the notes of the version you start on.

To know which version you are coming from, the database records the version the
application was opened with last time (`version_vista` in `preferencias`). The first time
you update from a version earlier than 1.8.0 this was not yet recorded: the update is
then known from the updater's log, but not always which version it came from, and only
the notes for the version reached are shown.

If there is no internet connection, or GitHub does not respond, it carries on with the
current version: that is not skipping the update; there simply was no answer. And if
installation fails, it stays as it was, says so in a notice in the header and tries
again next time.

How it installs depends on which copy it is:

- **Working copy** (this folder, cloned from the repository): it downloads the zip that
  GitHub generates from the tag and replaces the code — `radar/`, `web/`, `radar.py`,
  `start.command`, `macos/` and the certificates — keeping the old version alongside as
  `.anterior` so you can roll back. Then the server restarts and, if you are in
  `Radar de Licitaciones.app`, the window is rebuilt with
  `herramientas/construir_app.py --forzar` and reopened. In the browser
  (`start.command`) the page reloads.
- **App received from someone**, which carries the program inside: there are no files to
  replace, so it downloads the **`.app` attached to the release**, verifies it — the
  SHA-256 that GitHub publishes, that it is the real application, with the version it
  claims — and leaves it ready in `~/Library/Application Support/Radar de Licitaciones`.
  When it closes, the window is swapped for the new one in the same place and opened. The
  data lives outside the app, so nothing is lost.

  If the app is in a folder your user cannot write to — Applications, without being an
  administrator — the swap fails, the old one reopens and it does not try again until
  the next day, to avoid a loop. In that case you need to download it from the release
  and drag it over the old one, like any Mac program.

### Publishing a version

What the updater looks at is the **latest release published on GitHub**, so pushing code
to the repository does not update anyone. To publish one:

1. Bump `__version__` in `radar/__init__.py`.
2. Rebuild the app, leave the compiled binary in the repository and package the `.app`
   to attach it:

   ```bash
   python3 herramientas/construir_app.py --forzar --prefabricar --zip
   ```

   `--prefabricar` updates `macos/prefabricado/radar`, which is where anyone without
   Apple's developer tools gets the native window from. `--zip` produces a
   "Radar de Licitaciones X.Y.Z.zip" and gives you its SHA-256.
3. **Attach that zip to the release.** It is what the packaged app downloads to update
   itself; it finds it by name, so it only needs to contain "Radar" and end in `.zip`.
   If you forget, those copies cannot update: they say so in a notice with the release
   page, and each person has to find the file by hand.
4. Tag the release with that same number. If they don't match, the updater refuses to
   install it — which is what you want when the package is not what it claims to be.

```bash
gh release create v1.1.0 --title "v1.1.0 — …" --notes "…"
```

**The notes are read inside the application**: they are what the start-up screen shows
as what is new after an update. Write them for the people who use it — what is new and
what it is for — with `##` for sections and `-` for lists. The SHA-256 line is not
shown.

For the working copy, what gets downloaded is the zip that GitHub generates from the tag
itself, not a file that has to be uploaded. And **the repository has to be public**:
otherwise the version check gets a 404 and nobody updates.

**Publishing a release publishes it to everyone at once**: the next time each colleague
opens the application, it will install itself without asking.

About the SHA-256, which has two halves that should not be confused.

For the **working copy**, no SHA is checked. It used to be — it looked for one in the
notes and required it to match — and that was a trap twice over: that zip is generated
by GitHub on the fly from the tag and its checksum can change without the code changing,
and the SHA the notes do carry is the `.app`'s. With v1.5.0 this blocked installation on
every working copy. The real defence is HTTPS against this repository.

For the **`.app` zip** it is different: you upload that file yourself and its hash is
stable. GitHub computes its own when it is uploaded (the attachment's `digest`) and that
is the one required; if GitHub did not provide one, the one printed by `--zip` and pasted
into the notes is accepted, which also lets anyone who receives the app by another route
check it.

### Keeping it up to date automatically

```bash
python3 radar.py programar --hora 8 --minuto 30
```

It creates a macOS task (`~/Library/LaunchAgents/com.licitaciones-radar.ingesta.plist`)
that downloads what is new every morning. It is **the only file this project writes
outside its folder**, and the command tells you which one before creating it. The log
goes to `data/ingest.log`. To remove it:

```bash
python3 radar.py programar --desinstalar
```

If you would rather do it by hand, `start.command` downloads and opens the inbox in one
go.

---

## Fine-tuning the search

From the **«Términos de búsqueda»** (Search terms) tab in the application. Each profile
has one box per term type, one word per line. Before saving, **«Ver qué cambiaría»**
(See what would change) tells you how many tenders come in and drop out with the new
terms, with examples: changing a word blind across more than a hundred thousand records
is the quickest way to fill the inbox with noise.

When you save, everything already downloaded is re-evaluated without downloading anything
again. A copy of the previous file is kept in `config/perfiles.anterior.json`.

You can also edit **`config/perfiles.json`** by hand and run `python3 radar.py match`;
it is the same file.

That file **is not version-controlled**: it is created automatically the first time by
copying `config/perfiles.ejemplo.json`, which is deliberately generic. The terms you
actually search with — the stems, the typos that appear in tender documents, the
variants in Spain's co-official languages — are your work, and they make the difference
between finding a contract and missing it. They stay on your machine, never go to the
repository and no update touches them.

There are three levels of terms, and the distinction is what makes the tool usable
rather than a dumping ground:

| Field | What it is for |
|---|---|
| `terminos_fuertes` | Strong terms, enough on their own: `phishing`, `dmarc`, `ingenieria social` (social engineering). |
| `terminos_debiles` | Ambiguous ones (`concienci`, awareness; `formacion`, training). They only count if something from `contexto_requerido` also appears. |
| `contexto_requerido` | What confirms it is about security: `ciberseguridad`, `malware`, `iso 27001`… |
| `cpv_prefijos` | Add points, but **never** accept a tender on their own. They narrow down the family: `72500000` covers the whole `725*` group, including `72514300`. |
| `excluir` | Overrides everything else. |
| `importe_minimo` | Only discards when the value is known. |
| `terminos_consulta` | What is sent as a query to TED and Catalonia, which filter on their own servers. |

Five things learnt from wrestling with the real data, which are worth respecting when
editing:

1. **Use stems, not whole words.** `conscienci` covers *conscienciar*, *conscienciació*
   and *concienciación* (awareness-raising). Tender documents use both the verb and the
   noun. Each term matches **at the start of a word and extends to the right**: the stem
   still works, but `formacion` no longer turns up inside «sistemas de
   in**formación**» (information systems). That detail is not cosmetic — when it was
   compared with a plain "is contained in", 612 of 943 matches in a real database had
   come in that way, and the «Por qué ha entrado» panel cited training that the tender
   documents never mentioned.
2. **Keep the typos.** `phising` with a single s appears as such in published tender
   documents; without that variant you lose real business.
3. **Catalan texts are in Catalan.** Include both forms (*ciberseguridad* and
   *ciberseguretat*). Accents make no difference.
4. **The trailing space counts.** `ens ` with a trailing space requires the standalone
   acronym: it matches «del ens incluido» and «els seus ens dependents», but not
   «ensayo» (test) or «enseñanza» (teaching). Without that space it would be a stem and
   would match «ensayo» (though no longer «defensa» or «bienes», because there the
   acronym sits in the middle of the word). The screen does not trim spaces, and warns
   you when a term of three letters or fewer has none.
5. **Watch out for short acronyms.** `spf` looked harmless and let in ten absurd
   tenders: sun protection for beach lifeguards, SPF laboratory mice and «Entidades
   SPF» (Sector Público Foral, a regional public-sector category). It is set as an
   ambiguous term, so it only gets in with security context.

And a warning: do not put generic words (`seguridad`, `email`) in `terminos_consulta`.
It was tried, and it made TED return more than 12,000 notices only to end up with the
same 200 good ones.

---

## What it covers

| Source | What it contributes |
|---|---|
| **PLACSP – licitaciones** (tenders) | Most of Spain: central government, regions, town and city councils. |
| **PLACSP – plataformas agregadas** (aggregated platforms) | The regions with their own platform, which PLACSP collects by aggregation: **the Basque Country, Navarre and Galicia**, as well as Catalonia, Andalusia, Madrid and La Rioja. |
| **PLACSP – consultas preliminares de mercado** (preliminary market consultations) | The public sector asking the market **before** writing the tender documents. That is where you can still influence things; by the time of the notice, all that is left is to compete. |
| **TED (European Union)** | Everything above the EU threshold, plus award notices (who won and for how much). |
| **Cataluña** (Catalonia) | Its own platform, with more detail than what arrives via aggregation: contract duration, lots and winning bidder. |

PLACSP's **minor contracts** (*contratos menores*, low-value contracts awarded directly)
are also available, disabled by default:

```bash
python3 radar.py ingest --fuente placsp:menores
```

We do not recommend them, and now that is based on a measurement rather than a hunch: in
a sample of **6,572 real minor contracts only 2 passed the filter** (0.03%), and one of
them had its value entered wrongly. This README used to say that awareness pilots lived
there; the data does not back that up. It is a lot of volume for almost nothing, and on
top of that most of them fall out anyway because of `importe_minimo`.

### What it does NOT cover

- **The contents of the tender document PDFs.** It searches the title, the subject and
  the description of the lots, not inside the documents. It is the improvement that
  would add the most precision and the first candidate for a second phase.
- **The region filter does not apply to TED notices.** TED does not expose any usable
  region field in its API (all the `place-performance-*` fields were tried), so its
  tenders appear without a region. For the other sources it works.
- **Post-award data from the regional portals.** Andalusia, the Valencian Community,
  Castilla y León, Asturias, the Canary Islands and Aragón publish their own CSV files
  and APIs, but **they are not new tenders**: they are records of contracts already
  signed. Castilla y León's includes in each row an `enlace_de_publicacion` pointing to
  `contrataciondelestado.es`, and the Generalitat Valenciana itself says it publishes
  its tenders on PLACSP. What they would add is `adjudicatario`, `fecha_formalizacion`
  and `plazo_de_ejecucion_meses`, which is exactly what the Vencimientos view is missing.
  Pending as an improvement to that view, not as a source of tenders.
- **Email or Slack alerts.** Inbox only: you have to go in and look. None of this has
  been written, not even half-started.
- **A shared instance.** Each person has their own database and triage.

On the native connector for Euskadi (the Basque Country): it was investigated and **is
not needed**. Its API exists (`api.euskadi.eus` responds) but it does not publish the
procurement endpoint, and every route tried returns 403 or 404. Analysing the
aggregated-platforms dataset showed that it already covers the Basque Country, Navarre
and Galicia with complete fields, so enabling it came free and with less maintenance than
writing three connectors.

And on looking for more tender sources in general: **there is nowhere else to look**.
Article 347 of the LCSP (Spain's Public Sector Contracts Act) requires every tender
notice to be published on PLACSP or on a regional platform interconnected with it, so a
tender that is not on PLACSP does not legally exist. What was measured when checking
this: the aggregated platforms cover Catalonia, Andalusia, the Basque Country, Madrid,
Galicia, Navarre and La Rioja; **the other ten regions come through
`placsp:licitaciones`**, not through the aggregated ones. If you see little volume from
Valencia, Castilla y León, Aragón or Murcia, it is not a connector that is missing: it
is the history of `placsp:licitaciones`.

```bash
python3 radar.py ingest --fuente placsp:licitaciones --backfill 2024,2025,2026
```

---

## What to expect from the filter

Over a 2024–2026 history the filter lets through **less than one ten-thousandth of what
it downloads**: 519 notices out of 686,302. It is a deliberately narrow filter, and that
is the underlying decision: the inbox is calibrated for what is being sold — awareness
and email protection — and not for cybersecurity in general.

The reference configuration comes with four profiles and **only three active**:

| Profile | Notices | |
|---|---|---|
| Concienciación y phishing (Awareness and phishing) | 412 | the niche: simulations, training, security culture |
| Protección del correo electrónico (Email protection) | 107 | DMARC, gateways, anti-phishing, anti-spam |
| Consultas previas al mercado (Preliminary market consultations) | 0 today | a watch: flags any preliminary consultation in the niche when it comes out |
| ~~Ciberseguridad y seguridad de la información~~ (Cybersecurity and information security) | disabled | SOC, ENS, pentesting, managed security |

The fourth is **disabled on purpose**, and it is worth knowing why: it contributed 3,123
of the 3,780 matches there were before, four out of every five records in the inbox, and
none of them was something we could bid for. If one day the catalogue expands to more
general cybersecurity services, you re-enable it by ticking **«activo»** (active) in the
«Términos de búsqueda» tab and pressing **«Guardar y aplicar»** (Save and apply): its 41
terms are still in the file. On saving, everything downloaded is re-evaluated and the
profile appears immediately in the inbox drop-down, with its matches. By hand it is the
same: `"activo": true` in `config/perfiles.json` and run `match` again.

The **preliminary consultations** profile is at zero, and that is deliberate too. These
are preliminary market consultations, the only moment when you can still influence a
tender before it is written, so it is worth keeping the channel open even if nothing is
coming through it today. It was returning fourteen records until they were looked at one
by one: official gazettes, box-body trailers, UPS spare parts and IP data transport. Nine
of the fourteen got in only because the body publishing them is called «Agència de
Digitalització, **Ciberseguretat** i Telecomunicacions».

Which leads to the other thing that was fixed by measuring, and which should not be
broken again: **the name of the contracting body does not feed the rules**. What is
indexed for the search box does include it — searching for «Viladecans» has to work —
but what is evaluated is the subject, the description and the lots, and nothing else.
With the name included, «Instituto Nacional de **Ciberseguridad**», «Departament
d'Educació i **Formació** Professional» or «**Ens** d'Abastament d'Aigua Ter-Llobregat»
supplied the ambiguous term, the required context, or both, for free: they were 125 of
the 535 matches for the awareness profile, 23%, among them INCIBE's «Formación en
Gestión de Proyectos Europeos y soft-skills» and building works for a prefabricated
module. None of the 125 carried a strong term, so removing the contracting body did not
cost a single true positive. It lives in `Licitacion.texto_reglas`, with the tests in
`tests/test_reevaluacion.py`.

If you still find there is noise, tighten `contexto_requerido` or raise
`importe_minimo`.

An example of what it does find and what would otherwise be missed: a hardware
maintenance contract from Viladecans City Council whose **lot 10** was «programa de
conscienciació en CIBERSEGURETAT» (cybersecurity awareness programme). Neither the title
nor the CPV code gives it away; it appears because the text of the lots is indexed too.

On durations: they are converted respecting the unit declared by the source. Every so
often the buyer itself makes a mistake and publishes "36 años" (36 years) where it meant
"36 meses" (36 months). It is stored exactly as it arrives rather than corrected on our
side, so if you see an absurd duration in the expiring contracts view, the error is in
the original notice.

---

## If something goes wrong

**Start with `python3 radar.py doctor`.** It takes a second and checks in one go what
lies behind almost every problem: the Python version, that the certificate store is
still valid, free disk space, that the database opens and is up to date, that the search
terms are valid, that no source has failed, that no lock left by a dead download is
blocking searches, that the cache has no unreadable ZIPs and that the morning task is
actually loaded. Everything that is not right comes with the command that fixes it.

It does not touch anything: it opens the database read-only and creates or migrates
nothing. Two checks have to be requested separately because they are not instant:

```bash
python3 radar.py doctor --integridad   # ¿la base está dañada? lee los 3 GB: ~50 s
python3 radar.py doctor --con-red      # ¿hay una versión nueva publicada?
```

**The app stays on «Arrancando el radar…» (Starting the radar…).** It means the Python
server never responded. To see why, launch the binary from the terminal instead of
double-clicking: it writes what it finds to standard error — the project folder, which
Python it chose, whether it managed to launch the server.

```bash
"./Radar de Licitaciones.app/Contents/MacOS/radar"
```

The usual cause is that no Python 3.9+ is installed; the app does not bundle it and
macOS no longer ships with it. The other is a half-built copy of the app, without the
program inside: rebuilding it fixes that. Meanwhile, `start.command` still works.

**`python3 radar.py estado`** tells you when each source last ran, what it fetched and
whether it failed. The inbox shows a red notice at the top when a source breaks: without
that notice, "there are no tenders this week" and "the connector is broken" look the
same.

**Certificate / TLS error when downloading from PLACSP.** The macOS certificate store
does not include the FNMT root (the certificate authority of Spain's Royal Mint) that
signs PLACSP, so the project carries its own `config/certs/ca-bundle.pem`. If it
expires:

```bash
pip install --upgrade certifi && python3 herramientas/regenerar_ca_bundle.py
```

Certificate verification is never disabled; the script aborts if the new bundle does not
contain the Spanish roots.

**I changed a profile and what I expected isn't showing up.** `match` only re-evaluates
what has already been downloaded. If the new term has to be sent as a query to TED or
Catalonia:

```bash
python3 radar.py ingest --reiniciar-cursor --dias 365
```

**I want to start from scratch.** Delete the `data/` folder and run `ingest` again.
Triage and notes live there, so they are lost.

**The database takes up a lot of space.** With the full history it is about 3 GB,
because it holds hundreds of thousands of tenders. It is not shared when you pass the
folder to a colleague: `data/` is in the `.gitignore` on purpose, and each person builds
their own, with their own triage and notes. If you are not interested in the history,
delete `data/` and do a normal ingestion, without `--primera-carga`: you will be left
with the window of the last few days.

And the history ZIPs are kept in `data/cache/` so they are not downloaded again, which is
another **5.3 GB**: between the two, `data/` reaches 8.5 GB. `python3 radar.py estado`
tells you how much they take up and `python3 radar.py estado --limpiar-cache` deletes
them without losing any data — they will be downloaded again the next time you ask for
history. `.parcial` files may also appear there: these are downloads cut off halfway,
kept in case the server ever allows them to be resumed. `--limpiar-cache` removes those
too, and deleting them loses nothing.

ZIPs for closed years are never requested again, because they no longer change. The
current year's is: PLACSP rewrites it every day, so if the one you have saved is more
than a day old, the next `--backfill` or `--primera-carga` refreshes it. And if that
download fails, it carries on using the old one, with a warning in the log, rather than
leaving you with nothing.

**I was on an earlier version.** Nothing to do: on start-up any missing columns are
added and the grouping keys are recalculated without downloading again, keeping triage
and notes. The first ingestion will mark many tenders as "updated" — it is just that more
fields are stored now — but the change history does not fill with noise: a new revision is
only recorded when the status, the winning bidder or the value changes.

---

## How it is built

Python 3 with **zero external dependencies** (standard library only) and a static front
end with no build step. That is deliberate: anyone can clone the folder and start without
installing anything.

With one exception, which is worth stating clearly: the native macOS window is a
compiled Swift program, and its binary **is in the repository** (`macos/prefabricado/`).
It is not a dependency — nothing in Python needs it, and `start.command` works just as
well without it — but it is the only part of this project that cannot be read before it
is run. It was committed because a GitHub release zip only contains source files, and a
colleague without Apple's developer tools installed could not compile it. The source sits
alongside it, in `macos/Radar.swift`, and is rebuilt with
`python3 herramientas/construir_app.py`.

Project layout (descriptions in Spanish, as in the code):

```
radar.py              punto de entrada de la línea de comandos
radar/
  rutas.py            dónde está el código y dónde se escriben los datos
  net.py              descargas con TLS verificado, reintentos y reanudación
  model.py            el modelo común al que traducen todas las fuentes
  db.py               SQLite: esquema, migraciones, dedup e historial
  matching.py         el motor de reglas
  consultas.py        las consultas de las vistas, la analítica y el CSV
  pipeline.py         orquesta la ingesta: qué fuentes, en qué orden, por etapas
  server.py           servidor local (solo 127.0.0.1)
  busqueda.py         lanza la ingesta en segundo plano y su cerrojo
  progreso.py         el indicador de la terminal y la instantánea que lee la app
  programar.py        la tarea diaria de macOS
  actualizacion.py    traer una versión nueva sin salir de la aplicación
  diagnostico.py      las comprobaciones de `radar.py doctor`
  sources/            un conector por fuente, independientes entre sí
config/perfiles.json  tus búsquedas guardadas — esto es lo que se edita (no se versiona)
config/perfiles.ejemplo.json  la plantilla genérica de la que se crea el anterior
web/                  la interfaz
macos/Radar.swift     la ventana nativa: arranca el servidor y lo enseña
macos/icono.svg       el icono, en texto; se rasteriza al montar la app
macos/prefabricado/   el binario ya compilado, para quien no tenga las herramientas
herramientas/construir_app.py  monta «Radar de Licitaciones.app»
tests/                442 pruebas, con datos reales de las fuentes como fixtures
data/radar.db         la base (se crea sola; aquí vive tu triaje)
data/cache/           los ZIP del histórico, para no volver a bajarlos
data/busqueda.log     lo que va contando la descarga lanzada desde la aplicación
```

The connectors are isolated on purpose: if Catalonia changes its schema one morning, the
rest of the ingestion keeps working and the inbox says so.

**`radar/rutas.py` deserves a paragraph**, because it is what makes it possible to
distribute the program as a single file. For a long time everything hung off the project
folder: `radar/` lived there, and so did `data/radar.db`. For a copy cloned from the
repository that is fine, and it is still what happens. What it did not allow was putting
the code inside a `.app`, because you cannot write there. So there are two roots, not
one: `CODIGO`, which is read from — `web/`, the certificates, the profile template — and
`DATOS`, which is written to — the database, the cache, each user's `perfiles.json`. The
rule that separates them is in the module's docstring and is summarised in the "Where
your data lives" table above.

If a file that the program writes ever needs to be added, it goes in `DATOS`. If it is
something that is only read, in `CODIGO`. Putting it in the wrong place does not fail in
a working copy — both roots are the same there — and does fail in the packaged app, which
is the worst place to find out.

```bash
python3 -m unittest discover -s tests -t .
```

They also run on every push, on Python 3.9 — the minimum stated above, and the one that
breaks without anyone noticing on a machine with a newer Python — and on 3.13, on Linux
and macOS. The recipe is in `.github/workflows/tests.yml`.

The tests include verified real tenders (among them LANTIK's awareness office, €915,000,
and a phishing platform with no CPV code and no clue other than the typo «phising») and
a collection of observed false positives — environmental awareness, road safety,
occupational risk prevention, «sistemas de información» that is not «formación», sun
cream with SPF 50 — which must stay out. If you touch `matching.py` or the profiles,
those tests tell you whether you have broken the precision.

And there is a group among the ones that must NOT get in, even though they are genuine
cybersecurity contracts: the Ministry of Culture's cybersecurity office (€1,031,857),
the information security contract of the Seguridad Social (Spain's social security
system, €22.9 million) and an ENS and SOC support contract. They used to get in, and
rightly so; what changed was not the matcher but the catalogue. They are there to warn
if someone re-enables the broad profile by mistake.

One of them deserves special attention:
`test_los_terminos_casan_a_principio_de_palabra_pero_siguen_siendo_raices` pins down two
halves of the matcher's behaviour that balance each other out. If you ever think the
matcher should use `\b` on both sides of each term, that test fails on its second half:
closing off the end breaks the stem design that half the configuration depends on.
