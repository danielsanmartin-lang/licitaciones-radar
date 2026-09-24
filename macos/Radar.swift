// El envoltorio nativo: una ventana de macOS con la bandeja dentro.
//
// Lo que arregla es el arranque. Hasta ahora había que hacer doble clic en
// `start.command`, que deja una ventana de Terminal abierta —y quien la cierra por
// costumbre se lleva el servidor por delante— y la aplicación en una pestaña del
// navegador, entre las otras treinta. Esto es un icono en el Dock.
//
// Deliberadamente NO reimplementa nada. Toda la lógica sigue en Python y la interfaz
// sigue siendo `web/`: esto arranca `radar.py serve`, espera a que conteste y lo enseña
// en un WKWebView. El día que haya que cambiar la bandeja se cambia el HTML, como
// antes, sin recompilar nada.
//
// Se compila con las Command Line Tools, sin Xcode:
//
//     python3 herramientas/construir_app.py
//
// Dos cosas que parecen detalles y no lo son, explicadas donde ocurren: el menú
// «Edición» hay que construirlo a mano o no funcionan ⌘C y ⌘V dentro de la web, y al
// salir hay que matar el servidor pero NO la ingesta.

import AppKit
import WebKit

// MARK: - Registro

/// Traza a stderr. Invisible al hacer doble clic, legible al arrancar el binario a mano:
///
///     "Radar de Licitaciones.app/Contents/MacOS/radar"
///
/// Existe porque la primera versión se quedaba en «Arrancando el radar…» sin decir por
/// qué, y desde fuera no había manera de saber si el problema era Python, la carpeta o
/// el puerto.
func traza(_ mensaje: String) {
    FileHandle.standardError.write(Data("[radar] \(mensaje)\n".utf8))
}

// MARK: - Configuración

enum Ajustes {
    static let puerto = 8811
    static let host = "127.0.0.1"
    static var base: URL { URL(string: "http://\(host):\(puerto)/")! }

    /// Donde está el programa: la carpeta que tiene `radar.py`.
    ///
    /// Se mira en dos sitios, y el orden importa:
    ///
    /// 1. **`Contents/Resources` del propio bundle.** Es el caso normal: el `.app` se
    ///    lleva el código dentro, así que es un único fichero que se arrastra a
    ///    Aplicaciones y se manda por correo. Los datos no van ahí —dentro de un bundle
    ///    no se escribe— y de eso se encarga `radar/rutas.py`, que al verse dentro de
    ///    un `.app` manda la base y los perfiles a `~/Library/Application Support`.
    /// 2. **Al lado del bundle.** Es el caso de quien trabaja en el proyecto: se compila
    ///    la app en la carpeta del repositorio y se quiere que use ESE código y ESA
    ///    base, no una copia congelada dentro del bundle. Sin esto, cada cambio en el
    ///    Python obligaría a volver a montar la app para verlo.
    static func raizProyecto() -> URL? {
        let fm = FileManager.default
        let tiene = { (u: URL) in
            fm.fileExists(atPath: u.appendingPathComponent("radar.py").path)
        }

        // Una copia de trabajo manda sobre la copia empaquetada: si el .app está dentro
        // del repositorio, se desarrolla contra el repositorio.
        var candidata = Bundle.main.bundleURL.deletingLastPathComponent()
        for _ in 0..<5 {
            if tiene(candidata) { return candidata }
            candidata = candidata.deletingLastPathComponent()
        }

        if let recursos = Bundle.main.resourceURL, tiene(recursos) { return recursos }
        return nil
    }
}

/// La versión que dice el código Python, leyendo la línea de `radar/__init__.py`.
///
/// Es la misma técnica que usa `actualizacion._version_del_arbol()`, y por el mismo
/// motivo: para saber un número no hay que ejecutar nada.
func versionDelProyecto() -> String? {
    guard let raiz = Ajustes.raizProyecto(),
          let texto = try? String(contentsOf: raiz.appendingPathComponent("radar/__init__.py"),
                                  encoding: .utf8)
    else { return nil }
    for linea in texto.split(separator: "\n") where linea.hasPrefix("__version__") {
        return linea.split(separator: "=", maxSplits: 1).last?
            .trimmingCharacters(in: CharacterSet(charactersIn: " \"'\t\r"))
    }
    return nil
}

/// La versión de este bundle.
func versionDelBundle() -> String {
    Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"
}

// MARK: - Localizar Python

enum Python {
    /// Dónde buscar, en orden. Homebrew primero porque en un Mac de desarrollo es el
    /// que está actualizado.
    static let candidatos = [
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
    ]

    /// El primer Python 3.9+ que de verdad arranque.
    ///
    /// No basta con que el fichero exista, y esto es exactamente lo que documenta
    /// `start.command`: macOS trae en `/usr/bin/python3` un lanzador que está ahí
    /// aunque Python no lo esté, y al invocarlo abre el instalador de las herramientas
    /// de Xcode y falla. Así que se comprueba ejecutándolo.
    static func localizar() -> String? {
        var aProbar = candidatos
        // Y lo que diga el PATH del usuario, por si tiene pyenv o un conda.
        if let delPath = conWhich() { aProbar.insert(delPath, at: 0) }

        for ruta in aProbar where FileManager.default.isExecutableFile(atPath: ruta) {
            if valeLaVersion(ruta) { return ruta }
        }
        return nil
    }

    private static func conWhich() -> String? {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        p.arguments = ["python3"]
        let salida = Pipe()
        p.standardOutput = salida
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return nil }

        // Se VACÍA la tubería antes de esperar, no después. Al revés es el bloqueo
        // clásico: si el hijo escribe más de lo que cabe en el búfer de la tubería
        // (unos 64 KB) se queda parado esperando que alguien lea, el padre se queda
        // parado en `waitUntilExit()` esperando que el hijo acabe, y la aplicación no
        // llega nunca a abrir la ventana. Con `which python3` no pasa —son cuarenta
        // bytes— pero es una trampa que no cuesta nada desarmar, y el arranque es
        // justo el sitio donde un bloqueo no se puede ni diagnosticar.
        let datos = salida.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()

        guard p.terminationStatus == 0 else { return nil }
        let texto = String(decoding: datos, as: UTF8.self)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return texto.isEmpty ? nil : texto
    }

    private static func valeLaVersion(_ ruta: String) -> Bool {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: ruta)
        p.arguments = ["-c", "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"]
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return false }
        p.waitUntilExit()
        return p.terminationStatus == 0
    }
}

// MARK: - El servidor

/// Arranca `radar.py serve` y lo para al salir.
final class Servidor {
    private var proceso: Process?
    /// Cierto cuando el servidor ya estaba en marcha antes de abrir la app: entonces no
    /// es nuestro y no se para al salir. Pasa al abrir la app teniendo ya un
    /// `start.command` corriendo, y matarle el servidor a otro proceso sería grosero.
    private(set) var ajeno = false

    /// ¿Contesta ya algo en el puerto?
    ///
    /// Se pregunta por `/api/resumen` y no solo por que el socket acepte conexiones:
    /// el `ThreadingHTTPServer` acepta desde el primer momento, pero la primera
    /// consulta contra una base de 3,3 GB tarda lo suyo, y cargar la página antes de
    /// que la API conteste enseña una bandeja vacía que luego se rellena de golpe.
    static func responde(timeout: TimeInterval = 1.5) -> Bool {
        var url = URLComponents(string: "http://\(Ajustes.host):\(Ajustes.puerto)/api/resumen")!
        url.queryItems = nil
        var peticion = URLRequest(url: url.url!)
        peticion.timeoutInterval = timeout
        peticion.cachePolicy = .reloadIgnoringLocalCacheData

        let espera = DispatchSemaphore(value: 0)
        var ok = false
        let tarea = URLSession.shared.dataTask(with: peticion) { _, respuesta, _ in
            ok = (respuesta as? HTTPURLResponse)?.statusCode == 200
            espera.signal()
        }
        tarea.resume()
        _ = espera.wait(timeout: .now() + timeout + 0.5)
        return ok
    }

    enum Fallo: Error, LocalizedError {
        case sinPython
        case sinProyecto
        case noArranca(String)

        var errorDescription: String? {
            switch self {
            case .sinPython:
                return """
                No encuentro un Python 3.9 o superior, y sin él esto no arranca.

                macOS ya no lo trae: Apple lo retiró del sistema en Catalina, así que en \
                un Mac recién estrenado hay que instalarlo una vez desde \
                python.org/downloads/macos. Si usas Homebrew: brew install python3
                """
            case .sinProyecto:
                return """
                Esta copia de la aplicación está incompleta: no lleva el programa dentro.

                Vuelve a montarla con «python3 herramientas/construir_app.py», o pide \
                una copia nueva a quien te la pasó.
                """
            case .noArranca(let motivo):
                return "El servidor no ha llegado a contestar.\n\n\(motivo)"
            }
        }
    }

    func arrancar() throws {
        traza("comprobando si ya hay un servidor en \(Ajustes.puerto)…")
        if Servidor.responde() {
            traza("sí: se reutiliza")
            // Ya hay uno. Se reutiliza en lugar de fallar por el puerto ocupado: es lo
            // que hace que abrir la app dos veces no monte dos servidores.
            ajeno = true
            return
        }
        guard let raiz = Ajustes.raizProyecto() else {
            traza("no encuentro radar.py ni dentro del bundle ni al lado "
                  + "(\(Bundle.main.bundleURL.path))")
            throw Fallo.sinProyecto
        }
        traza("proyecto en \(raiz.path)")
        guard let python = Python.localizar() else {
            traza("ningún Python 3.9+ utilizable")
            throw Fallo.sinPython
        }
        traza("python en \(python)")

        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        // `-B`: que Python no escriba `__pycache__`. No es una optimización, es una
        // condición: el código vive dentro del .app, y escribir ahí invalida la firma
        // —medido: 17 ficheros añadidos y `codesign --verify` en rojo tras el primer
        // arranque— además de no poder hacerse si la app está en /Applications, que no
        // es del usuario.
        p.arguments = ["-B", "-u", "radar.py", "serve",
                       "--sin-navegador", "--puerto", String(Ajustes.puerto)]
        p.currentDirectoryURL = raiz

        // Y lo mismo por entorno, porque la ingesta la lanza `radar/busqueda.py` como
        // otro proceso con `sys.executable` y sin `-B`: la variable sí la hereda, el
        // argumento no. Se parte del entorno heredado en lugar de fijar uno nuevo para
        // no dejar al hijo sin PATH ni HOME.
        var entorno = ProcessInfo.processInfo.environment
        entorno["PYTHONDONTWRITEBYTECODE"] = "1"
        p.environment = entorno
        // La salida del servidor no se lee: lo que importa lo cuenta la propia bandeja,
        // y un Pipe que nadie vacía acaba bloqueando al hijo cuando llena el búfer.
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch {
            traza("no se pudo lanzar: \(error.localizedDescription)")
            throw Fallo.noArranca(error.localizedDescription)
        }
        proceso = p
        traza("servidor lanzado (pid \(p.processIdentifier))")
    }

    /// Espera a que conteste, sondeando. Devuelve en el hilo principal.
    func esperar(hasta segundos: Int = 90, listo: @escaping (Result<Void, Error>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            for _ in 0..<segundos {
                if Servidor.responde() {
                    DispatchQueue.main.async { listo(.success(())) }
                    return
                }
                // Si el proceso se ha muerto, no tiene sentido seguir esperando 90 s.
                if let p = self?.proceso, !p.isRunning {
                    let codigo = p.terminationStatus
                    DispatchQueue.main.async {
                        listo(.failure(Fallo.noArranca(
                            "El proceso de Python terminó con el código \(codigo). "
                            + "Prueba a arrancarlo a mano con «python3 radar.py serve» "
                            + "para ver qué dice.")))
                    }
                    return
                }
                Thread.sleep(forTimeInterval: 1)
            }
            DispatchQueue.main.async {
                listo(.failure(Fallo.noArranca("Ha pasado \(segundos) s sin respuesta.")))
            }
        }
    }

    /// El PID del servidor si es nuestro, o 0. Lo necesita el script que vuelve a abrir
    /// la app: tiene que esperar a que este servidor suelte el puerto, o la app nueva lo
    /// encontraría todavía contestando, lo daría por «ajeno» y se quedaría sin servidor
    /// en cuanto terminara de morirse.
    var pidPropio: Int32 {
        guard !ajeno, let p = proceso, p.isRunning else { return 0 }
        return p.processIdentifier
    }

    /// Para el servidor. NO toca la ingesta.
    ///
    /// `radar/busqueda.py` lanza la descarga como un proceso aparte y desligado, a
    /// propósito: dura horas y tiene que sobrevivir al cierre de la terminal. Aquí solo
    /// se termina el hijo que hemos arrancado nosotros —el servidor—, así que una carga
    /// en marcha sigue bajando datos después de cerrar la ventana, que es justo lo que
    /// promete el mensaje de `start.command`.
    func parar() {
        guard !ajeno, let p = proceso, p.isRunning else { return }
        p.terminate()
        // Un margen corto para que cierre el socket y suelte la base; si no se va,
        // se le deja, porque colgar el cierre de la app es peor.
        for _ in 0..<20 where p.isRunning { Thread.sleep(forTimeInterval: 0.05) }
    }
}

// MARK: - La aplicación

final class Delegado: NSObject, NSApplicationDelegate, WKNavigationDelegate,
                      WKUIDelegate, WKDownloadDelegate, WKScriptMessageHandler {
    private let servidor = Servidor()
    private var ventana: NSWindow!
    private var web: WKWebView!
    private var aviso: NSTextField!

    // MARK: Ciclo de vida

    func applicationDidFinishLaunching(_ notification: Notification) {
        construirMenu()
        construirVentana()

        // Primero lo propio: si el código ya es de una versión más nueva que esta
        // ventana, se rehace y se vuelve a abrir antes de arrancar nada. Lo de preguntar
        // a GitHub por versiones nuevas lo hace después la pantalla de arranque de la web.
        if ponerAlDiaLaVentana() { return }
        arrancarServidor()
    }

    private func arrancarServidor() {
        do {
            try servidor.arrancar()
        } catch {
            mostrarFalloYSalir(error)
            return
        }

        aviso.isHidden = false
        aviso.stringValue = servidor.ajeno
            ? "Conectando con el radar que ya estaba en marcha…"
            : "Arrancando el radar…"

        servidor.esperar { [weak self] resultado in
            guard let self else { return }
            switch resultado {
            case .success:
                self.aviso.isHidden = true
                self.web.isHidden = false
                self.web.load(URLRequest(url: Ajustes.base))
            case .failure(let error):
                self.mostrarFalloYSalir(error)
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        servidor.parar()
    }

    /// Es una app de una sola ventana: sin ella no hay nada que representar, y dejarla
    /// viva dejaría el servidor de Python corriendo sin que se vea por ningún sitio.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    // MARK: Ventana

    private func construirVentana() {
        ventana = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1280, height: 860),
            styleMask: [.titled, .closable, .resizable, .miniaturizable, .fullSizeContentView],
            backing: .buffered, defer: false)
        ventana.title = "Radar de Licitaciones"
        ventana.titlebarAppearsTransparent = false
        // Por debajo de esto la bandeja empieza a apilar los filtros en cuatro líneas.
        ventana.minSize = NSSize(width: 820, height: 560)
        // Recuerda tamaño y posición sin que haya que guardar preferencias a mano.
        ventana.setFrameAutosaveName("ventana-radar")

        let configuracion = WKWebViewConfiguration()
        // El servidor manda `Cache-Control: no-store`, pero un almacén persistente
        // igualmente guardaría el localStorage de la bandeja —el orden elegido, los
        // avisos descartados— que es justo lo que se quiere conservar entre arranques.
        configuracion.websiteDataStore = .default()
        // El puente con la pantalla de arranque: cuando instala una versión nueva, es la
        // web la que sabe que ha terminado y la ventana la única que puede cerrarse y
        // volver a abrirse. `window.webkit.messageHandlers.radar.postMessage(…)`.
        configuracion.userContentController.add(self, name: "radar")

        web = WKWebView(frame: ventana.contentView!.bounds, configuration: configuracion)
        web.autoresizingMask = [.width, .height]
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = false
        // El inspector web, para poder mirar la consola cuando algo no pinta. Es una
        // herramienta interna; no hay motivo para esconderlo.
        if web.responds(to: Selector(("setInspectable:"))) {
            web.setValue(true, forKey: "inspectable")
        }
        web.isHidden = true

        aviso = NSTextField(labelWithString: "")
        aviso.alignment = .center
        aviso.font = .systemFont(ofSize: 13)
        aviso.textColor = .secondaryLabelColor
        aviso.translatesAutoresizingMaskIntoConstraints = false

        let contenedor = NSView(frame: ventana.contentView!.bounds)
        contenedor.addSubview(web)
        contenedor.addSubview(aviso)
        NSLayoutConstraint.activate([
            aviso.centerXAnchor.constraint(equalTo: contenedor.centerXAnchor),
            aviso.centerYAnchor.constraint(equalTo: contenedor.centerYAnchor),
        ])
        ventana.contentView = contenedor

        ventana.center()
        ventana.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func mostrarFalloYSalir(_ error: Error) {
        aviso.isHidden = false
        web.isHidden = true
        aviso.stringValue = error.localizedDescription

        let alerta = NSAlert()
        alerta.alertStyle = .critical
        alerta.messageText = "No se ha podido abrir el radar"
        alerta.informativeText = error.localizedDescription
        alerta.addButton(withTitle: "Cerrar")
        alerta.beginSheetModal(for: ventana) { _ in NSApp.terminate(nil) }
    }

    // MARK: Menú
    //
    // Entero a mano, porque un binario de `swiftc` no tiene nib y `NSApp.mainMenu`
    // empieza vacío.
    //
    // El menú «Edición» NO es decorativo y es el que más fácil se olvida: los atajos de
    // cortar, copiar, pegar y seleccionar todo dentro de un WKWebView los sirve el
    // *first responder* a través de estos items. Sin el menú, ⌘C y ⌘V no hacen nada en
    // la caja de búsqueda ni en el área de notas de la ficha, y la app parece rota sin
    // que haya ningún error en ninguna parte.

    private func construirMenu() {
        let principal = NSMenu()

        let nombre = "Radar de Licitaciones"
        let mApp = NSMenuItem()
        let app = NSMenu()
        app.addItem(withTitle: "Acerca de \(nombre)",
                    action: #selector(acercaDe), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(withTitle: "Buscar novedades ahora",
                    action: #selector(buscarAhora), keyEquivalent: "r")
            .keyEquivalentModifierMask = [.command, .shift]
        app.addItem(.separator())
        app.addItem(withTitle: "Ocultar \(nombre)",
                    action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        app.addItem(withTitle: "Ocultar los demás",
                    action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
            .keyEquivalentModifierMask = [.command, .option]
        app.addItem(.separator())
        app.addItem(withTitle: "Salir de \(nombre)",
                    action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        mApp.submenu = app
        principal.addItem(mApp)

        let mEdicion = NSMenuItem()
        let edicion = NSMenu(title: "Edición")
        edicion.addItem(withTitle: "Deshacer", action: Selector(("undo:")), keyEquivalent: "z")
        edicion.addItem(withTitle: "Rehacer", action: Selector(("redo:")), keyEquivalent: "Z")
        edicion.addItem(.separator())
        edicion.addItem(withTitle: "Cortar", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edicion.addItem(withTitle: "Copiar", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edicion.addItem(withTitle: "Pegar", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edicion.addItem(withTitle: "Seleccionar todo",
                        action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        mEdicion.submenu = edicion
        principal.addItem(mEdicion)

        let mVer = NSMenuItem()
        let ver = NSMenu(title: "Ver")
        ver.addItem(withTitle: "Recargar", action: #selector(recargar), keyEquivalent: "r")
        ver.addItem(.separator())
        ver.addItem(withTitle: "Aumentar el texto", action: #selector(masTexto), keyEquivalent: "+")
        ver.addItem(withTitle: "Reducir el texto", action: #selector(menosTexto), keyEquivalent: "-")
        ver.addItem(withTitle: "Tamaño original", action: #selector(textoNormal), keyEquivalent: "0")
        ver.addItem(.separator())
        ver.addItem(withTitle: "Pantalla completa",
                    action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
            .keyEquivalentModifierMask = [.command, .control]
        mVer.submenu = ver
        principal.addItem(mVer)

        let mVentana = NSMenuItem()
        let ventanaMenu = NSMenu(title: "Ventana")
        ventanaMenu.addItem(withTitle: "Minimizar",
                            action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        ventanaMenu.addItem(withTitle: "Zoom",
                            action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        ventanaMenu.addItem(.separator())
        ventanaMenu.addItem(withTitle: "Cerrar",
                            action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        mVentana.submenu = ventanaMenu
        principal.addItem(mVentana)
        NSApp.windowsMenu = ventanaMenu

        let mAyuda = NSMenuItem()
        let ayuda = NSMenu(title: "Ayuda")
        ayuda.addItem(withTitle: "Abrir el README en el navegador",
                      action: #selector(abrirReadme), keyEquivalent: "")
        ayuda.addItem(withTitle: "Mostrar la carpeta del programa",
                      action: #selector(mostrarCarpeta), keyEquivalent: "")
        mAyuda.submenu = ayuda
        principal.addItem(mAyuda)
        NSApp.helpMenu = ayuda

        NSApp.mainMenu = principal
    }

    // MARK: Acciones del menú

    @objc private func acercaDe() {
        let version = versionDelBundle()
        let alerta = NSAlert()
        alerta.messageText = "Radar de Licitaciones \(version)"
        alerta.informativeText = """
        Licitaciones de concienciación en ciberseguridad y protección del correo \
        publicadas por la administración pública española.

        Los datos y la interfaz los sirve el propio programa en Python; esta ventana \
        solo lo arranca y lo enseña.
        """
        alerta.addButton(withTitle: "Cerrar")
        alerta.beginSheetModal(for: ventana, completionHandler: nil)
    }

    @objc private func recargar() { web.reload() }
    @objc private func masTexto() { web.pageZoom = min(web.pageZoom + 0.1, 2.5) }
    @objc private func menosTexto() { web.pageZoom = max(web.pageZoom - 0.1, 0.6) }
    @objc private func textoNormal() { web.pageZoom = 1 }

    /// Pulsa el botón «Buscar ahora» de la bandeja en lugar de llamar a la API.
    ///
    /// Así hay un solo camino: el mismo que el del botón, con sus avisos, su barra de
    /// progreso y su comprobación de que no haya ya una carga en marcha. Duplicar la
    /// llamada aquí significaría mantener dos.
    @objc private func buscarAhora() {
        web.evaluateJavaScript("document.getElementById('buscar-ahora')?.click()")
    }

    @objc private func abrirReadme() {
        guard let raiz = Ajustes.raizProyecto() else { return }
        NSWorkspace.shared.open(raiz.appendingPathComponent("README.md"))
    }

    @objc private func mostrarCarpeta() {
        guard let raiz = Ajustes.raizProyecto() else { return }
        NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: raiz.path)
    }

    // MARK: Versiones
    //
    // La instalación en sí la hacen Python y la pantalla de arranque de la web, sin
    // preguntar: al abrir, si hay versión nueva, se instala. Aquí solo queda lo que no
    // puede hacer nadie más que la ventana, que es cerrarse y volver a abrirse —ya con
    // el .app rehecho o cambiado por el nuevo—. No hay menú ni diálogo de «Actualizar»:
    // una actualización que se puede dejar para luego se deja para siempre.

    /// Marca con la que se vuelve a abrir la app tras rehacerse o cambiarse. Evita un
    /// bucle si, por lo que sea, el .app rehecho sigue sin cuadrar con el código.
    static let marcaRelanzada = "--relanzada"

    /// ¿Esta ventana se puede rehacer desde el código que está usando?
    ///
    /// Solo en una copia de trabajo, y solo si el .app que corre es el que monta
    /// `construir_app.py` —el de la raíz del proyecto—: rehacer otro no cambiaría este.
    /// En la app empaquetada no hace falta nunca: su versión y la de su código son la
    /// misma por construcción, y la que se actualiza es la app entera.
    private func sePuedeRehacer() -> Bool {
        guard let raiz = Ajustes.raizProyecto(),
              raiz.standardizedFileURL != Bundle.main.resourceURL?.standardizedFileURL,
              FileManager.default.fileExists(
                atPath: raiz.appendingPathComponent("herramientas/construir_app.py").path)
        else { return false }
        let esperado = raiz.appendingPathComponent("Radar de Licitaciones.app")
        return esperado.standardizedFileURL.path == Bundle.main.bundleURL.standardizedFileURL.path
    }

    /// Si el código es más nuevo que esta ventana, se rehace y se vuelve a abrir sola.
    ///
    /// Pasa cuando la versión nueva se instaló con la ventana vieja —por la terminal,
    /// con `radar.py actualizar`, o con una ventana de antes de que esto existiera—.
    /// Antes se ofrecía con un «Rehacer ahora / Más tarde»; ahora no se pregunta. Si
    /// rehacerla falla, se sigue con la vieja, que funciona igual: el shell no depende
    /// de la versión de Python, solo la dice mal en «Acerca de».
    ///
    /// Devuelve `true` si se está rehaciendo; entonces no hay que arrancar nada más.
    private func ponerAlDiaLaVentana() -> Bool {
        let delBundle = versionDelBundle()
        guard let delProyecto = versionDelProyecto() else {
            traza("no he podido leer la versión de radar/__init__.py")
            return false
        }
        traza("versión: bundle \(delBundle) · proyecto \(delProyecto)")
        guard delProyecto != delBundle,
              !CommandLine.arguments.contains(Delegado.marcaRelanzada),
              sePuedeRehacer()
        else { return false }

        traza("el bundle se ha quedado atrás; lo rehago")
        aviso.isHidden = false
        aviso.stringValue = "Poniendo al día la ventana para la versión \(delProyecto)…"
        rehacerApp { [weak self] ok, texto in
            guard let self else { return }
            if ok {
                self.relanzar()
            } else {
                traza("no se pudo rehacer: \(texto.suffix(400))")
                self.arrancarServidor()
            }
        }
        return true
    }

    /// `construir_app.py --forzar` en segundo plano. Vuelve en el hilo principal.
    private func rehacerApp(listo: @escaping (Bool, String) -> Void) {
        guard let raiz = Ajustes.raizProyecto(), let python = Python.localizar() else {
            listo(false, "no encuentro el proyecto o Python")
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: python)
            p.arguments = ["herramientas/construir_app.py", "--forzar"]
            p.currentDirectoryURL = raiz
            let salida = Pipe()
            p.standardOutput = salida
            p.standardError = salida
            var texto = ""
            var ok = false
            do {
                try p.run()
                // Se lee antes de esperar, por lo mismo que en `conWhich()`.
                let datos = salida.fileHandleForReading.readDataToEndOfFile()
                p.waitUntilExit()
                texto = String(decoding: datos, as: UTF8.self)
                ok = p.terminationStatus == 0
            } catch {
                texto = error.localizedDescription
            }
            DispatchQueue.main.async { listo(ok, texto) }
        }
    }

    /// Cierra la app y la vuelve a abrir, cambiándola antes por `nueva` si se da.
    ///
    /// Lo hace un script aparte porque un programa no puede sustituirse ni abrirse a sí
    /// mismo mientras corre: espera a que esta app y su servidor hayan terminado, mueve
    /// el bundle viejo a un lado, pone el nuevo en su sitio y lo abre. Si el cambio
    /// falla —una app en /Applications sin ser administrador—, devuelve la vieja a su
    /// sitio, deja escrito el motivo en `fallo` para que Python no lo reintente en
    /// bucle, y abre la vieja.
    private func relanzar(sustituyendoPor nueva: URL? = nil, version: String = "",
                          fallo: URL? = nil) {
        let script = """
        APP_PID="$1"; SERVIDOR_PID="$2"; DESTINO="$3"; NUEVA="$4"; FALLO="$5"; VERSION="$6"
        while kill -0 "$APP_PID" 2>/dev/null; do sleep 0.2; done
        n=0
        while [ "$SERVIDOR_PID" != 0 ] && kill -0 "$SERVIDOR_PID" 2>/dev/null && [ $n -lt 50 ]; do
          sleep 0.2; n=$((n+1))
        done
        if [ -n "$NUEVA" ]; then
          APARTE="$(dirname "$NUEVA")/anterior-$$.app"
          if ERR=$(mv "$DESTINO" "$APARTE" 2>&1); then
            if ERR=$(mv "$NUEVA" "$DESTINO" 2>&1); then
              rm -rf "$APARTE"
              rm -f "$FALLO"
              xattr -dr com.apple.quarantine "$DESTINO" 2>/dev/null
            else
              mv "$APARTE" "$DESTINO"
              printf '%s\\n%s\\n' "$VERSION" "$ERR" > "$FALLO"
            fi
          else
            printf '%s\\n%s\\n' "$VERSION" "$ERR" > "$FALLO"
          fi
        fi
        exec /usr/bin/open "$DESTINO" --args \(Delegado.marcaRelanzada)
        """
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/sh")
        p.arguments = ["-c", script, "radar-relanzar",
                       String(ProcessInfo.processInfo.processIdentifier),
                       String(servidor.pidPropio),
                       Bundle.main.bundleURL.path,
                       nueva?.path ?? "",
                       fallo?.path ?? "/dev/null",
                       version]
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do {
            try p.run()
        } catch {
            simpleAlerta("No se ha podido volver a abrir la aplicación",
                         "Ciérrala y ábrela a mano. \(error.localizedDescription)")
            return
        }
        traza("relanzando (script pid \(p.processIdentifier))")
        NSApp.terminate(nil)
    }

    // MARK: Mensajes de la web

    func userContentController(_ controlador: WKUserContentController,
                               didReceive mensaje: WKScriptMessage) {
        // Solo la bandeja propia puede pedir esto. Cualquier otra página ya se abre en
        // el navegador (ver la navegación), pero el puente no se fía de eso.
        guard mensaje.frameInfo.request.url?.host == Ajustes.host,
              let datos = mensaje.body as? [String: Any],
              let accion = datos["accion"] as? String
        else { return }
        let version = datos["version"] as? String ?? ""
        traza("la web pide «\(accion)» (\(version))")

        switch accion {
        case "reiniciar":
            reiniciarTrasActualizar(version: version)
        case "instalar-app":
            instalarAppNueva(ruta: datos["ruta"] as? String ?? "", version: version)
        default:
            break
        }
    }

    /// Copia de trabajo recién actualizada: rehacer la ventana y volver a abrirla.
    ///
    /// Si el servidor no es nuestro —un `start.command` que ya estaba corriendo— se le
    /// pide antes que se reinicie él, porque al cerrarse esta ventana no se para y
    /// seguiría con el código viejo en memoria. Y si la ventana no se puede rehacer, el
    /// camino de reserva es el del navegador: reiniciar el servidor y recargar la página.
    private func reiniciarTrasActualizar(version: String) {
        let deReserva = { [weak self] in
            _ = self?.web.evaluateJavaScript("window.reiniciarServidorYRecargar()")
        }
        guard sePuedeRehacer() else { deReserva(); return }

        if servidor.ajeno {
            var peticion = URLRequest(url: Ajustes.base.appendingPathComponent("api/reiniciar"))
            peticion.httpMethod = "POST"
            peticion.timeoutInterval = 5
            URLSession.shared.dataTask(with: peticion).resume()
        }
        rehacerApp { [weak self] ok, texto in
            if ok {
                self?.relanzar()
            } else {
                traza("no se pudo rehacer: \(texto.suffix(400))")
                deReserva()
            }
        }
    }

    /// App empaquetada: cambiarla por la que ha dejado preparada Python.
    ///
    /// La ruta viene de la web, así que se comprueba antes de mover nada: que sea un
    /// .app, que sea ESTA aplicación —mismo identificador— y que esté en la carpeta de
    /// datos, que es donde la deja `actualizacion._preparar_app()`.
    private func instalarAppNueva(ruta: String, version: String) {
        // Con los enlaces resueltos en los dos lados: macOS quita o pone «/private»
        // delante de /tmp y /var según a quién se le pregunte, y comparar una ruta
        // resuelta con otra sin resolver rechaza la buena.
        let resuelta = { (ruta: String) in
            URL(fileURLWithPath: ruta).resolvingSymlinksInPath().path
        }
        let nueva = URL(fileURLWithPath: resuelta(ruta))
        // Donde deja los datos `radar/rutas.py`: Application Support, o RADAR_DATOS.
        let soporte = FileManager.default.urls(for: .applicationSupportDirectory,
                                               in: .userDomainMask).first?
            .appendingPathComponent("Radar de Licitaciones").path
        let permitidas = [soporte, ProcessInfo.processInfo.environment["RADAR_DATOS"]]
            .compactMap { $0 }.filter { !$0.isEmpty }.map { resuelta($0) + "/" }
        let nuestra = Bundle(url: nueva)?.bundleIdentifier == Bundle.main.bundleIdentifier
        guard nueva.pathExtension == "app", nuestra,
              permitidas.contains(where: { nueva.path.hasPrefix($0) })
        else {
            traza("rechazo instalar \(ruta)")
            simpleAlerta("No se ha instalado la versión nueva",
                         "La aplicación preparada no está donde se esperaba (\(ruta)).")
            return
        }
        // …/data/actualizacion/nueva/Radar de Licitaciones.app → …/data/actualizacion/fallo.txt
        let fallo = nueva.deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("fallo.txt")
        relanzar(sustituyendoPor: nueva, version: version, fallo: fallo)
    }

    private func simpleAlerta(_ titulo: String, _ texto: String) {
        let alerta = NSAlert()
        alerta.messageText = titulo
        alerta.informativeText = texto
        alerta.addButton(withTitle: "Cerrar")
        alerta.beginSheetModal(for: ventana, completionHandler: nil)
    }

    // MARK: Navegación

    /// Todo lo que no sea el propio radar se abre en el navegador de verdad.
    ///
    /// Las fichas llevan enlaces a la plataforma oficial y a los pliegos. Sin esto se
    /// navegaría a contrataciondelestado.es DENTRO de la ventana, y como aquí no hay
    /// barra de direcciones ni botón de atrás, la única salida sería cerrar la app.
    func webView(_ webView: WKWebView,
                 decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.allow); return
        }
        if url.host == Ajustes.host || url.scheme == "about" || url.scheme == "data" {
            decisionHandler(.allow)
        } else {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        traza("bandeja cargada (\(webView.url?.absoluteString ?? "?"))")
    }

    /// Si la página no carga hay que decirlo: un WKWebView que falla se queda en blanco
    /// y, sin barra de direcciones, no hay nada en pantalla que sugiera qué ha pasado.
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!,
                 withError error: Error) {
        traza("fallo al cargar: \(error.localizedDescription)")
        aviso.isHidden = false
        aviso.stringValue = "No se ha podido cargar la bandeja: \(error.localizedDescription)"
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        self.webView(webView, didFail: navigation, withError: error)
    }

    /// `target="_blank"`: los enlaces de la ficha lo llevan, y un WKWebView sin esto
    /// simplemente no hace nada al pulsarlos.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction,
                 windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    /// El CSV. `/api/export.csv` se sirve con `Content-Disposition: attachment`, así que
    /// WebKit lo trata como descarga en lugar de como navegación; sin delegado, pulsar
    /// «Exportar CSV» no hace absolutamente nada y no hay error que lo explique.
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse,
                 didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView,
                 decidePolicyFor navigationResponse: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        decisionHandler(navigationResponse.canShowMIMEType ? .allow : .download)
    }

    func download(_ download: WKDownload,
                  decideDestinationUsing response: URLResponse,
                  suggestedFilename: String,
                  completionHandler: @escaping (URL?) -> Void) {
        let descargas = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Downloads")
        var destino = descargas.appendingPathComponent(suggestedFilename)
        // Sin esto, exportar dos veces falla en silencio: WebKit cancela la descarga si
        // el fichero ya existe en lugar de sobrescribirlo.
        var n = 2
        let base = destino.deletingPathExtension().lastPathComponent
        let ext = destino.pathExtension
        while FileManager.default.fileExists(atPath: destino.path) {
            destino = descargas.appendingPathComponent(
                ext.isEmpty ? "\(base)-\(n)" : "\(base)-\(n).\(ext)")
            n += 1
        }
        completionHandler(destino)
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard let url = download.progress.fileURL else { return }
        // Rebote en el Dock, que es lo que dice «ya está» en una app de Mac.
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    func download(_ download: WKDownload, didFailWithError error: Error,
                  resumeData: Data?) {
        simpleAlerta("No se ha podido guardar el CSV", error.localizedDescription)
    }
}

// MARK: - Arranque

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegado = Delegado()
app.delegate = delegado
app.run()
