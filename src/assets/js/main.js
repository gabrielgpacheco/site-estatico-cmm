(function () {
  "use strict";

  var CONSENT_KEY = "cmm_consent_v1";
  var body = document.body;
  var gaId = body.getAttribute("data-ga4") || "";
  var adsenseId = body.getAttribute("data-adsense") || "";
  var scriptsLoaded = { ga: false, ads: false };

  function $(selector, root) { return (root || document).querySelector(selector); }
  function $all(selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }

  /* ------------------------------------------------------------- navegação */
  var nav = $("#nav");
  var navToggle = $(".nav-toggle");
  if (nav && navToggle) {
    navToggle.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
      navToggle.setAttribute("aria-label", open ? "Fechar menu" : "Abrir menu");
    });
    $all("a", nav).forEach(function (link) {
      link.addEventListener("click", function () {
        nav.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
      });
    });
    document.addEventListener("click", function (event) {
      if (!nav.classList.contains("is-open")) return;
      if (nav.contains(event.target) || navToggle.contains(event.target)) return;
      nav.classList.remove("is-open");
      navToggle.setAttribute("aria-expanded", "false");
    });
  }

  $all(".nav__drop").forEach(function (drop) {
    drop.addEventListener("toggle", function () {
      if (!drop.open) return;
      $all(".nav__drop").forEach(function (other) {
        if (other !== drop) other.open = false;
      });
    });
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    if (nav) nav.classList.remove("is-open");
    if (navToggle) navToggle.setAttribute("aria-expanded", "false");
    var bar = $("#search-bar");
    if (bar) bar.hidden = true;
    var toggle = $(".search-toggle");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
    closeConsent();
  });

  var searchToggle = $(".search-toggle");
  var searchBar = $("#search-bar");
  if (searchToggle && searchBar) {
    var searchClose = $(".search-bar__close", searchBar);
    searchToggle.addEventListener("click", function () {
      var willOpen = searchBar.hidden;
      searchBar.hidden = !willOpen;
      searchToggle.setAttribute("aria-expanded", willOpen ? "true" : "false");
      if (willOpen) {
        var input = $("#q-top");
        if (input) input.focus();
      }
    });
    if (searchClose) {
      searchClose.addEventListener("click", function () {
        searchBar.hidden = true;
        searchToggle.setAttribute("aria-expanded", "false");
        searchToggle.focus();
      });
    }
  }

  /* ------------------------------------------------------------- consentimento */
  var consent = $("#consent");

  function readConsent() {
    try {
      var raw = window.localStorage.getItem(CONSENT_KEY);
      if (!raw) return null;
      var data = JSON.parse(raw);
      return data && (data.choice === "granted" || data.choice === "denied") ? data.choice : null;
    } catch (error) {
      return null;
    }
  }

  function writeConsent(choice) {
    try {
      window.localStorage.setItem(CONSENT_KEY, JSON.stringify({
        choice: choice,
        version: 1,
        date: new Date().toISOString()
      }));
    } catch (error) { /* armazenamento indisponível */ }
  }

  function showConsent() {
    if (!consent) return;
    consent.hidden = false;
    var first = $("[data-consent]", consent);
    if (first) first.focus();
  }

  function closeConsent() {
    if (consent) consent.hidden = true;
  }

  function injectScript(src, attrs) {
    return new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = src;
      script.async = true;
      Object.keys(attrs || {}).forEach(function (key) { script.setAttribute(key, attrs[key]); });
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  function loadAnalytics() {
    if (scriptsLoaded.ga || !gaId) return;
    scriptsLoaded.ga = true;
    window.gtag("js", new Date());
    window.gtag("config", gaId, { anonymize_ip: true });
    injectScript("https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(gaId));
  }

  function loadAds() {
    if (scriptsLoaded.ads || !adsenseId) return;
    if (!$(".ad-slot ins.adsbygoogle")) return;
    scriptsLoaded.ads = true;
    window.adsbygoogle = window.adsbygoogle || [];
    injectScript(
      "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=" + encodeURIComponent(adsenseId),
      { crossorigin: "anonymous" }
    ).then(function () {
      $all(".ad-slot ins.adsbygoogle").forEach(function () {
        window.adsbygoogle.push({});
      });
    }).catch(function () { /* bloqueado ou indisponível */ });
  }

  function grantConsent() {
    body.classList.add("consent-granted");
    if (window.gtag) {
      window.gtag("consent", "update", {
        ad_storage: "granted",
        ad_user_data: "granted",
        ad_personalization: "granted",
        analytics_storage: "granted"
      });
    }
    loadAnalytics();
    loadAds();
  }

  function denyConsent() {
    body.classList.remove("consent-granted");
    if (window.gtag) {
      window.gtag("consent", "update", {
        ad_storage: "denied",
        ad_user_data: "denied",
        ad_personalization: "denied",
        analytics_storage: "denied"
      });
    }
  }

  function setConsent(choice) {
    var previous = readConsent();
    writeConsent(choice);
    closeConsent();
    if (choice === "granted") {
      grantConsent();
    } else {
      denyConsent();
      if (previous === "granted") window.location.reload();
    }
  }

  $all("[data-consent]").forEach(function (button) {
    button.addEventListener("click", function () {
      setConsent(button.getAttribute("data-consent"));
    });
  });
  $all("[data-consent-open]").forEach(function (button) {
    button.addEventListener("click", showConsent);
  });

  var stored = readConsent();
  if (stored === "granted") {
    grantConsent();
  } else if (stored === "denied") {
    denyConsent();
  } else {
    showConsent();
  }

  /* --------------------------------------------------------- fachada de vídeo */
  document.addEventListener("click", function (event) {
    var button = event.target.closest(".video-facade__btn");
    if (!button) return;
    var facade = button.closest(".video-facade");
    var videoId = facade && facade.getAttribute("data-video");
    if (!facade || !videoId) return;
    var title = facade.getAttribute("data-title") || "Vídeo do YouTube";
    var iframe = document.createElement("iframe");
    iframe.src = "https://www.youtube-nocookie.com/embed/" + encodeURIComponent(videoId) + "?autoplay=1&rel=0";
    iframe.title = title;
    iframe.loading = "lazy";
    iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
    iframe.allowFullscreen = true;
    facade.innerHTML = "";
    facade.appendChild(iframe);
    facade.classList.add("is-playing");
    iframe.focus();
  });

  /* --------------------------------------------------------------- copiar link */
  $all("[data-copy-url]").forEach(function (button) {
    button.addEventListener("click", function () {
      var text = button.getAttribute("data-copy-url") || window.location.href;
      var done = function () {
        var original = button.textContent;
        button.textContent = "Link copiado!";
        button.classList.add("is-copied");
        window.setTimeout(function () {
          button.textContent = original;
          button.classList.remove("is-copied");
        }, 2200);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(function () {});
      } else {
        var area = document.createElement("textarea");
        area.value = text;
        area.setAttribute("readonly", "");
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        try { document.execCommand("copy"); done(); } catch (error) { /* ignore */ }
        document.body.removeChild(area);
      }
    });
  });

  /* --------------------------------------------------------------- Pagefind */
  var searchRoot = $("#search");
  if (searchRoot) {
    var css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "/pagefind/pagefind-ui.css";
    document.head.appendChild(css);

    injectScript("/pagefind/pagefind-ui.js").then(function () {
      if (!window.PagefindUI) throw new Error("Pagefind indisponível");
      new window.PagefindUI({
        element: "#search",
        showSubResults: true,
        showImages: false,
        resetStyles: false,
        translations: {
          placeholder: "Buscar no site…",
          clear_search: "Limpar",
          load_more: "Carregar mais resultados",
          search_label: "Buscar no site",
          filters: "Filtros",
          zero_matches: "Nenhum resultado encontrado."
        }
      });
      var query = new URLSearchParams(window.location.search).get("q");
      if (query) {
        var visibleInput = document.getElementById("q");
        if (visibleInput) visibleInput.value = query;
        var input = $(".pagefind-ui__search-input", searchRoot);
        if (input) {
          input.value = query;
          input.dispatchEvent(new Event("input", { bubbles: true }));
        }
      }
    }).catch(function () {
      searchRoot.innerHTML = '<p class="empty-state">O índice de busca ainda não foi gerado neste build. Rode o gerador com <code>--pagefind</code>.</p>';
    });
  }
})();
