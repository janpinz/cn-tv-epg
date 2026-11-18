/* cn-tv-epg · 节目单查看器
 * 纯前端、零依赖，直接读取 ../dist/epg.json
 */
(function () {
  "use strict";

  var DATA_URLS = ["../dist/epg.json", "data/epg.json", "dist/epg.json"];
  var state = { data: null, group: null, date: null, channelId: null, query: "" };

  var el = {
    meta: document.getElementById("meta"),
    groups: document.getElementById("groups"),
    date: document.getElementById("date"),
    search: document.getElementById("search"),
    channels: document.getElementById("channels"),
    guide: document.getElementById("guide"),
    empty: document.getElementById("empty"),
    footer: document.getElementById("footer-stats")
  };

  // ---------------------------------------------------------------- 工具
  function parseDate(value) {
    return value ? new Date(value) : null;
  }

  function hhmm(date) {
    return String(date.getHours()).padStart(2, "0") + ":" + String(date.getMinutes()).padStart(2, "0");
  }

  function durationText(start, end) {
    if (!start || !end) return "";
    var mins = Math.round((end - start) / 60000);
    if (mins <= 0) return "";
    if (mins >= 60) {
      var h = Math.floor(mins / 60);
      var m = mins % 60;
      return m ? h + " 小时 " + m + " 分" : h + " 小时";
    }
    return mins + " 分钟";
  }

  function initials(name) {
    var latin = name.match(/[A-Za-z]+/g);
    if (latin && latin.length) return latin[0].slice(0, 3).toUpperCase();
    return name.slice(0, 2);
  }

  function dayRows(channelId, dateKey) {
    var rows = (state.data.programmes[channelId] || []).filter(function (row) {
      return row.date === dateKey;
    });
    return rows;
  }

  function channelById(id) {
    return state.data.channels.find(function (c) { return c.id === id; });
  }

  // ---------------------------------------------------------------- 渲染
  function renderMeta() {
    var stats = state.data.stats;
    var generated = new Date(state.data.generated_at);
    el.meta.textContent =
      "更新于 " + generated.toLocaleString("zh-CN", { hour12: false }) +
      " · " + stats.channels_with_data + "/" + stats.channels + " 个频道有节目数据 · 共 " +
      stats.programmes.toLocaleString("zh-CN") + " 条节目";
  }

  function renderGroups() {
    el.groups.innerHTML = "";
    state.data.groups.forEach(function (group) {
      var btn = document.createElement("button");
      btn.className = "tab";
      btn.type = "button";
      btn.textContent = group.name;
      btn.setAttribute("aria-selected", String(group.id === state.group));
      btn.addEventListener("click", function () {
        state.group = group.id;
        var first = group.channels.find(function (id) {
          return dayRows(id, state.date).length > 0;
        });
        state.channelId = first || group.channels[0] || null;
        renderAll();
      });
      el.groups.appendChild(btn);
    });
  }

  function renderDates() {
    el.date.innerHTML = "";
    state.data.dates.forEach(function (dateKey) {
      var option = document.createElement("option");
      option.value = dateKey;
      option.textContent = dateKey.replace(/^\d{4}-/, "") + " " + weekdayName(dateKey);
      option.selected = dateKey === state.date;
      el.date.appendChild(option);
    });
  }

  function weekdayName(dateKey) {
    var names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
    return names[new Date(dateKey + "T00:00:00+08:00").getDay()];
  }

  function matchesQuery(channel) {
    if (!state.query) return true;
    var q = state.query.toLowerCase();
    if ((channel.name + " " + channel.id).toLowerCase().indexOf(q) >= 0) return true;
    return dayRows(channel.id, state.date).some(function (row) {
      return row.title.toLowerCase().indexOf(q) >= 0;
    });
  }

  function renderChannels() {
    el.channels.innerHTML = "";
    var group = state.data.groups.find(function (g) { return g.id === state.group; });
    if (!group) return;

    var shown = 0;
    group.channels.forEach(function (id) {
      var channel = channelById(id);
      if (!channel) return;
      if (!matchesQuery(channel)) return;
      shown++;

      var rows = dayRows(id, state.date);
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "channel" + (rows.length ? "" : " empty-channel");
      btn.setAttribute("aria-current", String(id === state.channelId));

      var badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = initials(channel.name);

      var name = document.createElement("span");
      name.className = "name";
      name.textContent = channel.name;

      btn.appendChild(badge);
      btn.appendChild(name);

      if (!rows.length) {
        var none = document.createElement("span");
        none.className = "now";
        none.style.color = "#5b6878";
        none.textContent = "无数据";
        btn.appendChild(none);
      } else if (isLive(rows)) {
        var live = document.createElement("span");
        live.className = "now";
        live.textContent = "直播中";
        btn.appendChild(live);
      }

      btn.addEventListener("click", function () {
        state.channelId = id;
        renderChannels();
        renderGuide();
      });
      el.channels.appendChild(btn);
    });

    el.empty.hidden = shown !== 0;
  }

  function isLive(rows) {
    var now = Date.now();
    return rows.some(function (row) {
      var start = parseDate(row.start);
      var end = parseDate(row.end);
      return start && end && now >= start && now < end;
    });
  }

  function renderGuide() {
    el.guide.innerHTML = "";
    var channel = state.channelId ? channelById(state.channelId) : null;
    if (!channel) return;

    var rows = dayRows(channel.id, state.date);
    if (!rows.length) {
      el.empty.hidden = false;
      el.empty.textContent = "该频道在 " + state.date + " 暂无节目数据（来源未提供）";
      return;
    }
    el.empty.hidden = true;

    var head = document.createElement("div");
    head.className = "guide-head";
    var h2 = document.createElement("h2");
    h2.textContent = channel.name;
    var sub = document.createElement("span");
    sub.className = "sub";
    sub.textContent = state.date + " " + weekdayName(state.date) + " · 共 " + rows.length + " 个节目";
    head.appendChild(h2);
    head.appendChild(sub);
    el.guide.appendChild(head);

    var list = document.createElement("div");
    list.className = "rows";
    var now = Date.now();

    rows.forEach(function (row) {
      var start = parseDate(row.start);
      var end = parseDate(row.end);
      var div = document.createElement("div");
      div.className = "row";
      if (start && end && now >= start && now < end) div.classList.add("live");
      else if (end && now >= end) div.classList.add("past");

      var time = document.createElement("div");
      time.className = "time";
      time.textContent = start ? hhmm(start) : "--:--";

      var title = document.createElement("div");
      title.className = "title";
      title.textContent = row.title_base || row.title;
      if (row.episode) {
        var ep = document.createElement("span");
        ep.className = "ep";
        ep.textContent = row.episode;
        title.appendChild(ep);
      }

      var dur = document.createElement("div");
      dur.className = "dur";
      dur.textContent = durationText(start, end);

      div.appendChild(time);
      div.appendChild(title);
      div.appendChild(dur);
      list.appendChild(div);
    });

    el.guide.appendChild(list);
  }

  function renderFooter() {
    el.footer.textContent =
      "generator " + state.data.generator + " v" + state.data.version +
      " · 时区 " + state.data.timezone;
  }

  function renderAll() {
    renderGroups();
    renderChannels();
    renderGuide();
  }

  // ---------------------------------------------------------------- 启动
  el.date.addEventListener("change", function () {
    state.date = el.date.value;
    renderChannels();
    renderGuide();
  });

  el.search.addEventListener("input", function () {
    state.query = el.search.value.trim().toLowerCase();
    renderChannels();
  });

  // 依次尝试多个路径：本地开发用 ../dist/，GitHub Pages 上用 data/
  function loadData() {
    return DATA_URLS.reduce(function (chain, url) {
      return chain.catch(function () {
        return fetch(url, { cache: "no-store" }).then(function (response) {
          if (!response.ok) throw new Error("HTTP " + response.status);
          return response.json();
        });
      });
    }, Promise.reject(new Error("尚未加载")));
  }

  loadData()
    .then(function (data) {
      state.data = data;
      state.group = data.groups.length ? data.groups[0].id : null;
      state.date = data.dates[0] || new Date().toISOString().slice(0, 10);
      var firstGroup = data.groups.find(function (g) { return g.id === state.group; });
      var preferred = null;
      if (firstGroup) {
        preferred =
          firstGroup.channels.find(function (id) { return dayRows(id, state.date).length > 0; }) ||
          firstGroup.channels[0];
      }
      state.channelId = preferred;
      renderMeta();
      renderDates();
      renderAll();
      renderFooter();
      window.setInterval(function () { renderChannels(); renderGuide(); }, 60000);
    })
    .catch(function (error) {
      el.meta.textContent = "加载失败：" + error.message;
      el.guide.innerHTML =
        '<div class="empty">无法读取 dist/epg.json。<br>请在本目录运行 <code>python -m epg serve</code>，' +
        "然后访问 http://127.0.0.1:8899/web/index.html</div>";
    });
})();
