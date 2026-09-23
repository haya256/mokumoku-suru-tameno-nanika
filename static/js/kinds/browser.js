// 管理者が置いた任意ページのiframe。YouTubeと違い▶待ちはせず、置かれた瞬間に全員の画面で
// 読み込まれる(OBSのブラウザソースと同じ「常時表示のアンビエントウィジェット」という位置づけ)
registerKind({
  key: "browser",

  // iframeはエリアが割り当てられた瞬間(クリック不要)に作る。中身はrenderTile/resetTileが出し入れする
  buildTileParts(tile) {
    const browserFrame = document.createElement("div");
    browserFrame.className = "browser-frame";
    tile.browserFrame = browserFrame;
    tile.browserUrl = null;
    return [browserFrame];
  },

  resetTile(tile) {
    tile.browserUrl = null;
    tile.browserFrame.replaceChildren();
  },

  renderTile(tile, area, { focused }) {
    setClass(tile.el, `tile browser${focused}`);
    tile.label.textContent = area.name;
    tile.status.hidden = true;
    tile.browserFrame.setAttribute("aria-hidden", focused ? "false" : "true");
    // URLが変わっていなければ触らない。ここを毎ポーリング(2秒毎)で作り直すと無限リロードになる
    if (tile.browserUrl === area.url) return;
    tile.browserUrl = area.url;
    const iframe = document.createElement("iframe");
    iframe.src = area.url;
    iframe.title = area.name;
    iframe.referrerPolicy = "no-referrer";
    // allow-scripts+allow-same-originの組み合わせは「同一オリジンをsandbox化した場合」だけ
    // sandbox回避に使われる既知の抜け穴になる。ここは通常他ドメインのiframeなので安全な組み合わせだが、
    // 管理者が自分自身のもくもくサーバーのURLを指定した場合はこの前提が崩れ、埋め込んだページから
    // 親ウィンドウのlocalStorage(管理者合言葉を含む)を読めてしまいうる。ただしこれは管理者本人が
    // 自分のURLを自分に埋め込む自傷的なケースに限られ、第三者による権限昇格経路にはならない。
    // allow-top-navigation系は意図的に与えない(タブごと乗っ取る遷移を防ぐ)
    iframe.sandbox = "allow-scripts allow-same-origin allow-forms allow-popups";
    tile.browserFrame.replaceChildren(iframe);
  },

  area: {
    label: "ブラウザ", needsUrl: true, addLabel: "置く", delLabel: "片付ける",
    confirm: "このブラウザを片付けますか？", urlHint: "表示したいページのURL",
    nameHint: "表示名 (任意/未指定ならホスト名)", missingUrl: "表示したいページのURLを入力してください",
    embedWarning: "このページは外部サイトへの埋め込みを許可していない可能性があります。\nマスには置きましたが、参加者の画面では表示できないかもしれません。",
    title: a => a.url || "",
    text: a => `🌐 ${a.name}`,
  },
});
