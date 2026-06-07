  function eid(domain, name) {
    return "/" + domain + "/" + encodeURIComponent(name);
  }

  function entityStringParts(entity) {
    entity = typeof entity === "string" ? entity : "";
    var slash = entity.indexOf("/");
    if (slash > 0) {
      return {
        domain: entity.slice(0, slash),
        name: entity.slice(slash + 1)
      };
    }
    return null;
  }

  function productSettingEntityParts(key) {
    var spec = PRODUCT_SETTINGS && PRODUCT_SETTINGS[key];
    return entityStringParts(spec && spec.entity);
  }

  var endpoints = {};

  function registerManualEntityEndpoints() {
    if (!MANUAL_ENTITIES) return;
    Object.keys(MANUAL_ENTITIES).forEach(function (key) {
      var parts = entityStringParts(MANUAL_ENTITIES[key] && MANUAL_ENTITIES[key].entity);
      if (!parts) return;
      endpoints[key] = eid(parts.domain, parts.name);
    });
  }

  function registerStaticEntityEndpoints() {
    if (!STATIC_ENTITIES) return;
    Object.keys(STATIC_ENTITIES).forEach(function (key) {
      var parts = entityStringParts(STATIC_ENTITIES[key] && STATIC_ENTITIES[key].entity);
      if (!parts) return;
      endpoints[key] = eid(parts.domain, parts.name);
    });
  }

  function registerProductSettingEndpoints() {
    if (!PRODUCT_SETTINGS) return;
    Object.keys(PRODUCT_SETTINGS).forEach(function (key) {
      var parts = productSettingEntityParts(key);
      if (!parts) return;
      endpoints[key] = eid(parts.domain, parts.name);
    });
  }

  registerManualEntityEndpoints();
  registerStaticEntityEndpoints();
  registerProductSettingEndpoints();

  function post(url, params) {
    var fullUrl = params ? url + "?" + new URLSearchParams(params).toString() : url;
    return fetch(fullUrl, { method: "POST" }).then(function (r) {
      if (!r.ok) console.error("POST " + fullUrl + " failed: " + r.status);
      return r;
    }).catch(function (err) {
      console.error("POST " + fullUrl + " error:", err);
      showBanner("Failed to save setting", "error");
    });
  }

  function postScheduleWakeTimeout(value) {
    var seconds = normalizeScheduleWakeTimeout(value);
    post(endpoints.schedule_wake_timeout + "/set", { value: seconds });
  }
