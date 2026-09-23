// エリア(ワールドマップのマス)と部屋NPCの種別の登録簿。サーバー側の kinds/ と対になる。
// 新しい種別は static/js/kinds/ にファイルを1つ作って registerKind() を呼び、
// index.html にその<script>を1行足すだけでよい。種別が持てるものはすべて任意:
//
//   buildTileParts(tile)   全マスに1回だけ呼ばれ、マスに常設する部品(DOM要素の配列)を返す
//   resetTile(tile)        マスが別のエリアに明け渡されるときの後片付け
//   renderTile(tile, area, { focused, visible })   エリアとしてマスを描く
//   area                   ワールド設定パネルでの見せ方(無ければエリアには置けない)
//   renderCell(cell, o, { tile, roomLabel, charaUrl })   部屋の中の1セルを描く
//   cellFingerprint()      部屋を描き直すかどうかの判定に足す値(カレンダーの日付など)
//   renderStatus(container, o, roomLabel)   アバタークリックで開くステータスウィンドウの中身
//   npc                    NPC管理パネルでの見せ方(無ければNPCにはなれない)
//   errors                 サーバーのエラーコードに対する、この種別固有の説明文
//
// 各ファイルは読み込み時に登録するだけで、中の関数が呼ばれるのは全ファイルの読み込み後
// (初回描画以降)なので、world.js などの関数を参照してよい
const KINDS = {};

function registerKind(def) {
  KINDS[def.key] = def;
}

// 登録順(= index.htmlの<script>の順)がマスの部品の重なり順とワールド設定パネルの選択肢の順になる
const kindList = () => Object.values(KINDS);
const areaKinds = () => kindList().filter(k => k.area);
const npcKinds = () => kindList().filter(k => k.npc).sort((a, b) => a.npc.order - b.npc.order);

// ワールド設定パネルでの見せ方。知らない種別(設定の手編集など)はピアとして見せる
const areaSpec = kind => KINDS[kind]?.area || KINDS.peer.area;
// 部屋の中の住人。実参加者(kind未指定)や知らない種別はbasic(ふつうのキャラ)として扱う
const occupantKind = kind => (KINDS[kind]?.renderCell ? KINDS[kind] : KINDS.basic);
const npcSpec = kind => KINDS[kind]?.npc || KINDS.basic.npc;
