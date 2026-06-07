  function renderWizard() {
    var step = 1;
    immichApp.innerHTML = "";
    app.innerHTML = "";
    renderStartupDevicePage();
    var wrap = el("div", "fade-in");
    wrap.innerHTML =
      '<p class="subtitle">Let\'s connect your photo frame</p>';
    var steps = el("div", "wizard-steps");
    var s1 = el("div", "step active");
    var s2 = el("div", "step");
    steps.appendChild(s1);
    steps.appendChild(s2);
    wrap.appendChild(steps);

    var body = el("div");
    wrap.appendChild(body);
    immichApp.appendChild(wrap);

    function showStep() {
      body.innerHTML = "";
      if (step === 1) {
        s1.className = "step active";
        s2.className = "step";
        body.appendChild(renderStep1());
      } else {
        s1.className = "step done";
        s2.className = "step active";
        body.appendChild(renderStep2());
      }
    }

    function renderStep1() {
      var card = el("div", "card fade-in");
      card.innerHTML = "<h3>Connection</h3>";

      var f1 = field("Immich Server URL");
      var urlInput = input("url", S.immich_url, "http://192.168.0.1:2283");
      f1.appendChild(urlInput);
      card.appendChild(f1);

      var f2 = field("API Key");
      var grp = el("div", "input-group");
      var keyInput = input("password", S.api_key, "Your Immich API key");
      var showBtn = el("button", "btn btn-secondary");
      showBtn.textContent = "Show";
      showBtn.type = "button";
      showBtn.onclick = function () {
        var isPass = keyInput.type === "password";
        keyInput.type = isPass ? "text" : "password";
        showBtn.textContent = isPass ? "Hide" : "Show";
      };
      grp.appendChild(keyInput);
      grp.appendChild(showBtn);
      f2.appendChild(grp);
      card.appendChild(f2);

      var nav = el("div", "wizard-nav");
      var nextBtn = el("button", "btn btn-primary");
      nextBtn.textContent = "Connect";
      nextBtn.onclick = function () {
        var u = normalizeImmichUrl(urlInput.value);
        var k = keyInput.value.trim();
        if (!u || !k) return;
        nextBtn.disabled = true;
        nextBtn.textContent = "Saving\u2026";
        saveConnectionValue(endpoints.immich_url, u, true)
          .then(function () {
            return saveConnectionValue(endpoints.api_key, k, false);
          })
          .then(function () {
            return Promise.all([
              safeGet(endpoints.immich_url),
              safeGet(endpoints.api_key)
            ]);
          })
          .then(function (res) {
            var savedUrl = normalizeImmichUrl((res[0] && (res[0].value || res[0].state)) || "");
            var savedKey = (res[1] && (res[1].value || res[1].state)) || "";
            if (savedUrl !== u || !savedKey) throw new Error("verify_failed");
            S.immich_url = u;
            S.api_key = k;
            step = 2;
            showStep();
          })
          .catch(function () {
            nextBtn.disabled = false;
            nextBtn.textContent = "Connect";
            showBanner("Failed to save connection. Please try again.", "error");
          });
      };
      nav.appendChild(nextBtn);
      card.appendChild(nav);
      return card;
    }

    function renderStep2() {
      var card = el("div", "card fade-in");
      card.innerHTML = "<h3>Clock & timezone</h3>";

      var f1 = field("Clock Format");
      f1.appendChild(
        selectFromOptions(productSettingOptions("clock_format"), S.clock_format, function (v) {
          S.clock_format = v;
          post(endpoints.clock_format + "/set", { option: v });
        })
      );
      card.appendChild(f1);

      var f2 = field("Timezone");
      f2.appendChild(
        timezoneSelect(S.tz_options, S.timezone, function (v) {
          post(endpoints.timezone + "/set", { option: v });
          S.timezone = v;
        })
      );
      card.appendChild(f2);

      card.appendChild(ntpServersField());

      var nav = el("div", "wizard-nav");
      var backBtn = el("button", "btn btn-secondary");
      backBtn.textContent = "Back";
      backBtn.onclick = function () {
        step = 1;
        showStep();
      };
      var doneBtn = el("button", "btn btn-primary");
      doneBtn.textContent = "Done";
      doneBtn.onclick = function () {
        renderSettings();
      };
      nav.appendChild(backBtn);
      nav.appendChild(doneBtn);
      card.appendChild(nav);
      return card;
    }

    showStep();
  }

  function renderStartupDevicePage() {
    var wrap = el("div", "fade-in");
    wrap.appendChild(makeImportSettingsCard());
    app.appendChild(wrap);
  }

  // --- Settings ---
