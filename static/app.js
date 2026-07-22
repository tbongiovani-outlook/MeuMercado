/*
 * Recursos de experiência do Meu Mercado:
 *   - Modo escuro (tema claro/escuro) com persistência
 *   - Atalhos de teclado para navegação e ações rápidas
 *   - Aplicativo instalável (PWA) via service worker
 *   - Notificações no computador para pendências (perguntas/reclamações)
 * Escrito em JS puro (sem dependências) para funcionar offline.
 */
(function () {
    "use strict";

    var root = document.documentElement;

    // ---------------------------------------------------------------------
    // Tema claro/escuro
    // ---------------------------------------------------------------------
    function temaAtual() {
        return root.getAttribute("data-theme") === "dark" ? "dark" : "light";
    }

    function aplicarTema(tema) {
        root.setAttribute("data-theme", tema);
        try { localStorage.setItem("mm_theme", tema); } catch (e) { /* noop */ }
        var escuro = tema === "dark";
        var btn = document.getElementById("theme-toggle");
        var icone = document.getElementById("theme-icon");
        if (btn) btn.setAttribute("aria-pressed", escuro ? "true" : "false");
        if (icone) icone.textContent = escuro ? "☀️" : "🌙";
        var meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.setAttribute("content", escuro ? "#151a2c" : "#4f46e5");
    }

    function alternarTema() {
        aplicarTema(temaAtual() === "dark" ? "light" : "dark");
    }

    // Sincroniza o botão com o tema já aplicado no <head>.
    aplicarTema(temaAtual());
    var themeBtn = document.getElementById("theme-toggle");
    if (themeBtn) themeBtn.addEventListener("click", alternarTema);

    // ---------------------------------------------------------------------
    // Modal de atalhos de teclado
    // ---------------------------------------------------------------------
    var modal = document.getElementById("shortcuts");
    var modalClose = document.getElementById("shortcuts-close");

    function modalAberto() {
        return modal && !modal.hidden;
    }

    function abrirModal(abrir) {
        if (!modal) return;
        modal.hidden = !abrir;
    }

    if (modal) {
        if (modalClose) modalClose.addEventListener("click", function () { abrirModal(false); });
        modal.addEventListener("click", function (e) {
            if (e.target === modal) abrirModal(false);
        });
    }

    // ---------------------------------------------------------------------
    // Atalhos de teclado
    // ---------------------------------------------------------------------
    var ROTAS = {
        h: "/",
        i: "/caixa-entrada",
        a: "/anuncios",
        n: "/publicar",
        r: "/promocoes",
        v: "/vendas",
        p: "/pos-venda",
        d: "/agendamentos",
        c: "/configuracao"
    };

    var esperandoG = false;
    var gTimer = null;

    function digitando(el) {
        if (!el) return false;
        var tag = (el.tagName || "").toLowerCase();
        return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
    }

    function focarBusca() {
        var campo = document.querySelector(".list-filter, input[type='search']");
        if (campo) {
            campo.focus();
            return true;
        }
        return false;
    }

    document.addEventListener("keydown", function (e) {
        if (e.metaKey || e.ctrlKey || e.altKey) return;

        // Esc fecha o modal de atalhos.
        if (e.key === "Escape" && modalAberto()) {
            abrirModal(false);
            return;
        }
        if (digitando(e.target)) return;

        // "?" abre/fecha a ajuda de atalhos.
        if (e.key === "?") {
            e.preventDefault();
            abrirModal(!modalAberto());
            return;
        }
        if (modalAberto()) return;

        // Sequência "g" + tecla para navegar (estilo webmail).
        if (esperandoG) {
            esperandoG = false;
            if (gTimer) { clearTimeout(gTimer); gTimer = null; }
            var destino = ROTAS[e.key.toLowerCase()];
            if (destino) {
                e.preventDefault();
                window.location.href = destino;
            }
            return;
        }

        if (e.key === "g") {
            esperandoG = true;
            gTimer = setTimeout(function () { esperandoG = false; }, 1200);
            return;
        }
        if (e.key === "t") {
            e.preventDefault();
            alternarTema();
            return;
        }
        if (e.key === "/") {
            if (focarBusca()) e.preventDefault();
        }
    });

    // ---------------------------------------------------------------------
    // PWA — registra o service worker (instalação + cache offline)
    // ---------------------------------------------------------------------
    if ("serviceWorker" in navigator) {
        window.addEventListener("load", function () {
            navigator.serviceWorker.register("/sw.js").catch(function () {
                /* Sem service worker o app continua funcionando normalmente. */
            });
        });
    }

    // ---------------------------------------------------------------------
    // Notificações no computador (pendências)
    // ---------------------------------------------------------------------
    var notifBtn = document.getElementById("notif-toggle");

    function contarPendencias() {
        var total = 0;
        document.querySelectorAll(".nav__badge:not(.nav__badge--ok)").forEach(function (b) {
            var n = parseInt((b.textContent || "").trim(), 10);
            if (!isNaN(n)) total += n;
        });
        return total;
    }

    function avisarPendencias() {
        if (!("Notification" in window) || Notification.permission !== "granted") return;
        var total = contarPendencias();
        if (total <= 0) return;
        var ultimo = 0;
        try { ultimo = parseInt(localStorage.getItem("mm_notif_last") || "0", 10) || 0; } catch (e) { /* noop */ }
        if (total === ultimo) return;
        try { localStorage.setItem("mm_notif_last", String(total)); } catch (e) { /* noop */ }
        var n = new Notification("Meu Mercado", {
            body: total + " pendência(s) aguardando: perguntas/reclamações.",
            icon: "/static/favicon.svg",
            tag: "mm-pendencias"
        });
        n.onclick = function () {
            window.focus();
            window.location.href = "/pos-venda";
            n.close();
        };
    }

    function refletirEstadoNotif() {
        if (!notifBtn || !("Notification" in window)) return;
        notifBtn.hidden = false;
        var ativo = Notification.permission === "granted";
        notifBtn.setAttribute("aria-pressed", ativo ? "true" : "false");
        if (Notification.permission === "denied") {
            notifBtn.title = "Notificações bloqueadas pelo navegador";
        }
    }

    if (notifBtn && "Notification" in window) {
        refletirEstadoNotif();
        notifBtn.addEventListener("click", function () {
            if (Notification.permission === "granted") {
                avisarPendencias();
                return;
            }
            if (Notification.permission === "denied") return;
            Notification.requestPermission().then(function () {
                refletirEstadoNotif();
                avisarPendencias();
            });
        });
        // Ao abrir uma página, avisa se já houver permissão e pendências novas.
        avisarPendencias();
    }
})();
