(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const short = (value, n = 10) => value ? String(value).slice(0, n) : "—";
  const state = {
    server: "filesystem-prod",
    overview: null,
    revisions: [],
    timeline: [],
    checks: [],
    views: new Map(),
    selectedRevision: null,
    source: null,
    demo: new URLSearchParams(location.search).get("demo") === "1",
  };

  const demo = buildDemoData();

  function buildDemoData() {
    const base = "2026-09-15T10:";
    const revisions = [
      makeRevision("1f73d2a91c48", "9e702bbda2aa", base + "12:06Z", "stdio_proxy", "initial_discovery", [
        ["search_files", "sha-search-1"], ["read_file", "sha-read-1"], ["list_directory", "sha-list-1"],
        ["write_file", "sha-write-1"], ["move_file", "sha-move-1"], ["file_info", "sha-info-1"]
      ]),
      makeRevision("4b9a6625e441", "33749f0c9df1", base + "24:41Z", "stdio_proxy", "discovery", [
        ["search_files", "sha-search-2"], ["read_file", "sha-read-1"], ["list_directory", "sha-list-1"],
        ["write_file", "sha-write-1"], ["move_file", "sha-move-1"], ["file_info", "sha-info-1"]
      ]),
      makeRevision("88ab94e13c70", "c2d909b381ee", base + "37:18Z", "stdio_proxy", "list_changed_refresh", [
        ["search_files", "sha-search-3"], ["read_file", "sha-read-1"], ["list_directory", "sha-list-1"],
        ["write_file", "sha-write-2"], ["move_file", "sha-move-1"], ["file_info", "sha-info-1"],
        ["export_workspace", "sha-export-1"]
      ]),
      makeRevision("bb602ff7af41", "a9f61691ea33", base + "48:53Z", "stdio_proxy", "discovery", [
        ["search_files", "sha-search-4"], ["read_file", "sha-read-1"], ["list_directory", "sha-list-1"],
        ["write_file", "sha-write-2"], ["move_file", "sha-move-1"], ["file_info", "sha-info-1"],
        ["export_workspace", "sha-export-1"], ["remote_sync", "sha-sync-1"]
      ]),
      makeRevision("d9148ac3f092", "67ad2e020c4b", "2026-09-15T11:02:22Z", "stdio_proxy", "list_changed_refresh", [
        ["search_files", "sha-search-5"], ["read_file", "sha-read-1"], ["list_directory", "sha-list-1"],
        ["write_file", "sha-write-2"], ["move_file", "sha-move-1"], ["file_info", "sha-info-1"],
        ["export_workspace", "sha-export-2"], ["remote_sync", "sha-sync-1"], ["credential_bridge", "sha-cred-1"]
      ])
    ];

    const checks = [
      check(revisions[0], "pass", 4.2),
      check(revisions[1], "pass", 18.6),
      check(revisions[2], "review_required", 54.4),
      check(revisions[3], "review_required", 68.2),
      check(revisions[4], "review_required", 78.6)
    ];

    const views = {};
    views[revisions[0].revision_id] = view(revisions[0], null, checks[0], []);
    views[revisions[1].revision_id] = view(revisions[1], revisions[0], checks[1], [
      toolChange("search_files", [{path:"/description",kind:"modified"}])
    ]);
    views[revisions[2].revision_id] = view(revisions[2], revisions[1], checks[2], [
      toolChange("search_files", [{path:"/inputSchema/properties/context",kind:"added"},{path:"/description",kind:"modified"}]),
      toolChange("write_file", [{path:"/inputSchema/properties/overwrite",kind:"added"}])
    ], ["export_workspace"]);
    views[revisions[3].revision_id] = view(revisions[3], revisions[2], checks[3], [
      toolChange("search_files", [{path:"/description",kind:"modified"}])
    ], ["remote_sync"]);
    views[revisions[4].revision_id] = view(revisions[4], revisions[3], checks[4], [
      toolChange("search_files", [
        {path:"/description",kind:"modified"},
        {path:"/inputSchema/properties/api_token",kind:"added"},
        {path:"/inputSchema/required",kind:"modified"}
      ]),
      toolChange("export_workspace", [{path:"/description",kind:"modified"}])
    ], ["credential_bridge"]);

    const checkpointDelta = {
      added_tools:["export_workspace","remote_sync","credential_bridge"],
      removed_tools:[],
      modified_tools:[
        toolChange("search_files", [{path:"/description",kind:"modified"},{path:"/inputSchema/properties/api_token",kind:"added"}]),
        toolChange("write_file", [{path:"/inputSchema/properties/overwrite",kind:"added"}])
      ],
      unchanged_tools:["read_file","list_directory","move_file","file_info"],
      changed:true
    };

    const overview = {
      server_id:"filesystem-prod",
      latest_revision:revisions[4],
      latest_security_check:checks[4],
      freshness:{dirty:false,pending_signals:0,last_signal_at:"2026-09-15T11:02:18Z",last_refreshed_revision_id:revisions[4].revision_id},
      trusted_status:{
        revision_id:revisions[4].revision_id,
        untrusted_tools:["credential_bridge","export_workspace","remote_sync"],
        missing_trusted_tools:[],
        modified_from_trusted:[
          toolChange("search_files", [{path:"/description",kind:"modified"},{path:"/inputSchema/properties/api_token",kind:"added"}]),
          toolChange("write_file", [{path:"/inputSchema/properties/overwrite",kind:"added"}])
        ],
        unchanged_trusted_tools:["read_file","list_directory","move_file","file_info"],
        review_required:true
      },
      tool_count:9,
      latest_checkpoint:{
        checkpoint_id:"checkpoint-e0d3",server_id:"filesystem-prod",name:"release/2026.09.14",
        revision_id:revisions[1].revision_id,tree_hash:revisions[1].tree_hash,
        created_at:"2026-09-14T18:20:00Z",created_by:"security-reviewer",note:"Known-good tool surface before sync rollout."
      },
      checkpoint_delta:checkpointDelta,
      revisions_since_checkpoint:3,
      checkpoint_tree_matches:false
    };

    const timeline = [
      event("check:"+revisions[4].revision_id,"security_check","2026-09-15T11:02:23Z","Security check: review_required",revisions[4].revision_id,"review_required",{detector_name:"rule_baseline",withheld_tools:["search_files","credential_bridge"]}),
      event("revision:"+revisions[4].revision_id,"revision","2026-09-15T11:02:22Z","Observed revision via stdio_proxy (list_changed_refresh)",revisions[4].revision_id,null,{added_tools:["credential_bridge"],modified_tools:["search_files","export_workspace"]}),
      event("signal:91ab","catalog_signal","2026-09-15T11:02:18Z","Server announced a tools-list change",revisions[4].revision_id,"acknowledged",{}),
      event("review:445a","review","2026-09-15T10:51:10Z","Approved read_file by security-reviewer",revisions[3].revision_id,"approved",{reviewer:"security-reviewer"}),
      event("check:"+revisions[3].revision_id,"security_check","2026-09-15T10:48:54Z","Security check: review_required",revisions[3].revision_id,"review_required",{detector_name:"hybrid_semantic"}),
      event("revision:"+revisions[3].revision_id,"revision","2026-09-15T10:48:53Z","Observed revision via stdio_proxy (discovery)",revisions[3].revision_id,null,{added_tools:["remote_sync"],modified_tools:["search_files"]}),
      event("checkpoint:e0d3","checkpoint","2026-09-14T18:20:00Z","Created trusted checkpoint release/2026.09.14",revisions[1].revision_id,"trusted",{created_by:"security-reviewer"})
    ];

    return {overview,revisions,checks,views,timeline};
  }

  function makeRevision(id, tree, observed, channel, trigger, tools) {
    return {
      server_id:"filesystem-prod",revision_id:id.padEnd(64,"a"),tree_hash:tree.padEnd(64,"b"),
      observed_at:observed,parent_revision_id:null,protocol_version:"2026-07-28",
      origin:{channel,trigger,pending_change_signals:trigger === "list_changed_refresh" ? 1 : 0},
      tools:tools.map(([name,sha])=>({name,sha256:sha.padEnd(64,"c"),canonical_tool:{name,description:name.replaceAll("_"," ")}})),
      duplicate_tool_names:[]
    };
  }
  function check(rev, stateName, risk) {
    return {
      server_id:rev.server_id,revision_id:rev.revision_id,tree_hash:rev.tree_hash,checked_at:rev.observed_at,
      state:stateName,detector_name:"hybrid_semantic_temporal",policy_name:"DefaultPolicy",
      forwarded_tools:stateName==="pass"?rev.tools.map(t=>t.name):rev.tools.filter(t=>!["search_files","credential_bridge"].includes(t.name)).map(t=>t.name),
      withheld_tools:stateName==="pass"?[]:["search_files","credential_bridge"],
      tools:[
        {tool_name:"search_files",sha256:"f".repeat(64),action:stateName==="pass"?"allow":"require_reconsent",reason:"Semantic capability drift",change_class:stateName==="pass"?"C1":"C2",risk_score:risk,confidence:.88,abstained:false,temporal_cumulative_score:risk>50?63.4:12.2,temporal_exceeded:risk>65},
        ...(stateName==="pass"?[]:[{tool_name:"credential_bridge",sha256:"e".repeat(64),action:"require_reconsent",reason:"New sensitive capability",change_class:"C2",risk_score:72.2,confidence:.91,abstained:false,temporal_cumulative_score:72.2,temporal_exceeded:true}])
      ]
    };
  }
  function toolChange(name, fields){ return {tool_name:name,old_sha256:["1".repeat(64)],new_sha256:["2".repeat(64)],field_changes:fields}; }
  function view(rev, parent, security, modified, added=[]) {
    return {
      revision:rev,
      parent_delta:parent?{
        from_revision_id:parent.revision_id,to_revision_id:rev.revision_id,added_tools:added,removed_tools:[],
        modified_tools:modified,unchanged_tools:[],duplicate_names_added:[],duplicate_names_resolved:[],
        changed:Boolean(added.length||modified.length)
      }:null,
      security_check:security,is_latest:false,freshness:null
    };
  }
  function event(id,kind,time,summary,revision,severity,details){
    return {event_id:id,kind,occurred_at:time,server_id:"filesystem-prod",summary,revision_id:revision,tool_name:null,severity,details};
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
  }
  function formatTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat(undefined,{hour:"2-digit",minute:"2-digit",month:"short",day:"2-digit"}).format(date);
  }
  function relativeTime(value) {
    const date = new Date(value);
    const diff = Date.now()-date.getTime();
    if (Number.isNaN(diff)) return value;
    const mins=Math.round(diff/60000);
    if (Math.abs(mins)<60) return mins<=1?"just now":mins+"m ago";
    const hrs=Math.round(mins/60);
    if (Math.abs(hrs)<24) return hrs+"h ago";
    return Math.round(hrs/24)+"d ago";
  }
  function humanOrigin(origin) {
    if (!origin) return "unknown";
    const channel=(origin.channel||"adapter").replaceAll("_"," ");
    const trigger=(origin.trigger||"discovery").replaceAll("_"," ");
    return channel+" · "+trigger;
  }
  function securityClass(value) {
    if (value==="pass") return "pass";
    if (value==="blocked") return "blocked";
    return "review";
  }
  function maxRisk(check) {
    const values=(check?.tools||[]).map(x=>x.risk_score).filter(x=>typeof x==="number");
    return values.length?Math.max(...values):0;
  }

  function renderRiskDial(risk) {
    const dial=$("risk-dial");
    const value=$("risk-dial-value");
    if (!dial || !value) return;
    const bounded=Math.max(0,Math.min(100,Number(risk)||0));
    dial.style.setProperty("--risk-angle",(bounded*3.6)+"deg");
    dial.classList.remove("low","medium","high");
    dial.classList.add(bounded>=70?"high":bounded>=45?"medium":"low");
    value.textContent=bounded.toFixed(0);
  }

  function renderTrajectory(o) {
    const host=$("revision-trajectory");
    if (!host) return;

    const chronological=[...state.revisions].reverse().slice(-6);
    if (!chronological.length) {
      host.innerHTML='<div class="inspector-empty"><p>No revision risk history yet.</p></div>';
      return;
    }

    const width=430;
    const height=168;
    const left=28;
    const right=18;
    const top=18;
    const bottom=32;
    const innerW=width-left-right;
    const innerH=height-top-bottom;
    const xAt=(index)=>left+(chronological.length===1?innerW/2:(innerW*index/(chronological.length-1)));
    const yAt=(risk)=>top+innerH-(Math.max(0,Math.min(100,risk))*innerH/100);

    const points=chronological.map((revision,index)=>{
      const check=checkForRevision(revision.revision_id);
      const risk=maxRisk(check);
      return {
        revision,
        check,
        risk,
        x:xAt(index),
        y:yAt(risk),
      };
    });

    const linePoints=points.map(p=>p.x+","+p.y).join(" ");
    const areaPoints=[
      left+","+(top+innerH),
      ...points.map(p=>p.x+","+p.y),
      (left+innerW)+","+(top+innerH)
    ].join(" ");
    const checkpointId=o.latest_checkpoint?.revision_id;

    const grid=[0,25,50,75,100].map(value=>{
      const y=yAt(value);
      return '<line class="trajectory-grid-line" x1="'+left+'" y1="'+y+'" x2="'+(left+innerW)+'" y2="'+y+'"></line>';
    }).join("");

    const thresholds=
      '<line class="trajectory-threshold" x1="'+left+'" y1="'+yAt(45)+'" x2="'+(left+innerW)+'" y2="'+yAt(45)+'"></line>'+
      '<line class="trajectory-threshold high" x1="'+left+'" y1="'+yAt(70)+'" x2="'+(left+innerW)+'" y2="'+yAt(70)+'"></line>';

    const marks=points.map((p,index)=>{
      const stateName=p.check?.state||"unknown";
      const checkpoint=p.revision.revision_id===checkpointId
        ? '<text class="trajectory-checkpoint" x="'+p.x+'" y="'+(height-4)+'" text-anchor="middle">checkpoint</text>'
        : '';
      return checkpoint+
        '<circle class="trajectory-point '+escapeHtml(stateName)+'" cx="'+p.x+'" cy="'+p.y+'" r="5" style="animation-delay:'+(index*.045)+'s"></circle>'+
        '<text class="trajectory-risk-label" x="'+p.x+'" y="'+(p.y-10)+'" text-anchor="middle">'+p.risk.toFixed(0)+'</text>'+
        '<text class="trajectory-label" x="'+p.x+'" y="'+(height-18)+'" text-anchor="middle">'+short(p.revision.revision_id,5)+'</text>';
    }).join("");

    host.innerHTML=
      '<svg viewBox="0 0 '+width+' '+height+'" role="img" aria-label="Risk score across recent MCP revisions">'+
        grid+thresholds+
        '<polygon class="trajectory-area" points="'+areaPoints+'"></polygon>'+
        '<polyline class="trajectory-line" points="'+linePoints+'"></polyline>'+
        marks+
      '</svg>';
  }

  function renderSurfaceMap(o) {
    const host=$("surface-map");
    if (!host) return;

    const tools=o.latest_revision?.tools||[];
    if (!tools.length) {
      host.innerHTML='<div class="inspector-empty"><p>No tools in the current surface.</p></div>';
      return;
    }

    const trust=o.trusted_status||{};
    const modified=new Set((trust.modified_from_trusted||[]).map(item=>item.tool_name));
    const untrusted=new Set(trust.untrusted_tools||[]);
    const width=360;
    const height=190;
    const cx=180;
    const cy=94;
    const rx=126;
    const ry=66;
    const count=tools.length;

    const nodes=tools.map((tool,index)=>{
      const angle=(-Math.PI/2)+(Math.PI*2*index/count);
      const x=cx+Math.cos(angle)*rx;
      const y=cy+Math.sin(angle)*ry;
      const status=untrusted.has(tool.name)?"untrusted":modified.has(tool.name)?"modified":"trusted";
      return {tool,x,y,status,index};
    });

    const edges=nodes.map(node=>
      '<line class="surface-edge '+node.status+'" x1="'+cx+'" y1="'+cy+'" x2="'+node.x+'" y2="'+node.y+'"></line>'
    ).join("");

    const marks=nodes.map(node=>{
      const anchor=node.x<cx-12?"end":node.x>cx+12?"start":"middle";
      const offset=node.x<cx-12?-9:node.x>cx+12?9:0;
      const labelY=node.y<cy-12?node.y-9:node.y>cy+12?node.y+13:node.y+3;
      const label=toolLabel(node.tool.name,15);
      return '<circle class="surface-node '+node.status+'" cx="'+node.x+'" cy="'+node.y+'" r="5.5" style="animation-delay:'+(node.index*.035)+'s"></circle>'+
        '<text class="surface-node-label" x="'+(node.x+offset)+'" y="'+labelY+'" text-anchor="'+anchor+'">'+escapeHtml(label)+'</text>';
    }).join("");

    host.innerHTML=
      '<svg viewBox="0 0 '+width+' '+height+'" role="img" aria-label="Current MCP tools arranged by trust state">'+
        '<circle class="surface-center-ring" cx="'+cx+'" cy="'+cy+'" r="29"></circle>'+
        edges+
        '<circle class="surface-center" cx="'+cx+'" cy="'+cy+'" r="20"></circle>'+
        '<text class="surface-center-label" x="'+cx+'" y="'+(cy+3)+'" text-anchor="middle">MCP</text>'+
        marks+
      '</svg>'+
      '<div class="surface-map-legend">'+
        '<span><i class="legend-dot pass"></i> trusted</span>'+
        '<span><i class="legend-dot review"></i> modified</span>'+
        '<span><i class="legend-dot blocked"></i> new / untrusted</span>'+
      '</div>';
  }

  function toolLabel(value, max) {
    const text=String(value||"");
    return text.length>max?text.slice(0,max-1)+"…":text;
  }

  async function fetchJson(path) {
    const response=await fetch(path,{headers:{"Accept":"application/json"}});
    if (!response.ok) {
      const error=new Error("HTTP "+response.status+" for "+path);
      error.status=response.status;
      throw error;
    }
    return response.json();
  }

  async function loadAll() {
    setLive("connecting");
    const server=state.server.trim()||"filesystem-prod";
    $("breadcrumb-server").textContent=server;
    if (state.demo) {
      state.overview=structuredClone(demo.overview);
      state.revisions=structuredClone(demo.revisions).reverse();
      state.timeline=structuredClone(demo.timeline);
      state.checks=structuredClone(demo.checks);
      state.views=new Map(Object.entries(structuredClone(demo.views)));
      state.server="filesystem-prod";
      $("server-input").value=state.server;
      renderAll();
      setLive("demo");
      maybeOpenRequestedRevision();
      return;
    }

    try {
      const encoded=encodeURIComponent(server);
      const [overview,revisions,timeline,checks]=await Promise.all([
        fetchJson("/v1/servers/"+encoded+"/overview"),
        fetchJson("/v1/servers/"+encoded+"/revisions"),
        fetchJson("/v1/servers/"+encoded+"/timeline"),
        fetchJson("/v1/servers/"+encoded+"/checks")
      ]);
      state.overview=overview;
      state.revisions=[...revisions].reverse();
      state.timeline=timeline;
      state.checks=checks;
      state.views.clear();
      renderAll();
      connectEvents();
      maybeOpenRequestedRevision();
    } catch (error) {
      setLive("disconnected");
      showToast(error.status===404?"No revisions exist for this server yet.":"Could not load DriftGuard data.","error");
      renderEmptyServer();
    }
  }

  function renderAll() {
    renderOverview();
    renderRevisions();
    renderTimeline();
  }

  function maybeOpenRequestedRevision() {
    const requested = new URLSearchParams(location.search).get("inspect");
    if (!requested || !state.revisions.length) return;
    const revisionId = requested === "latest" ? state.revisions[0].revision_id : requested;
    window.setTimeout(() => openRevision(revisionId), 80);
  }

  function renderOverview() {
    const o=state.overview;
    if (!o) return;
    const check=o.latest_security_check;
    const currentState=check?.state||"unknown";
    const badge=$("hero-badge");
    badge.className="status-badge "+securityClass(currentState);
    badge.innerHTML='<span class="status-dot"></span>'+escapeHtml(currentState.replaceAll("_"," ").toUpperCase());

    const fresh=o.freshness||{};
    const catalog=$("catalog-badge");
    catalog.textContent=fresh.dirty?"CATALOG DIRTY":"CATALOG CLEAN";
    catalog.className="mini-badge "+(fresh.dirty?"":"clean");

    $("hero-copy").textContent=fresh.dirty
      ?"The server announced a tool-list change. DriftGuard is waiting for the refreshed catalog before trust can be re-established."
      :"Latest discovery is reconciled. Historical trust, drift, and approvals remain fully versioned.";
    $("latest-revision").textContent=short(o.latest_revision?.revision_id,12);

    $("metric-tools").textContent=o.tool_count ?? "—";
    $("metric-tools-note").textContent=(o.latest_revision?.duplicate_tool_names?.length||0)?"duplicate names detected":"complete catalog surface";

    const trust=o.trusted_status||{};
    const drift=(trust.untrusted_tools?.length||0)+(trust.modified_from_trusted?.length||0)+(trust.missing_trusted_tools?.length||0);
    $("metric-drift").textContent=drift;
    $("metric-drift-note").textContent=drift?"tool(s) need attention":"matches approved state";

    $("metric-ahead").textContent=o.revisions_since_checkpoint ?? "—";
    $("metric-ahead-note").textContent=o.latest_checkpoint?"since "+o.latest_checkpoint.name:"no checkpoint";

    const risk=maxRisk(check);
    $("metric-risk").textContent=risk?risk.toFixed(0):"0";
    $("metric-risk-note").textContent=risk>=70?"high-risk evidence":risk>=45?"review threshold":"within baseline";

    renderRiskDial(risk);
    renderTrajectory(o);
    renderSurfaceMap(o);
    renderCheckpoint(o);
    renderTrust(o);
  }

  function renderCheckpoint(o) {
    const cp=o.latest_checkpoint;
    const delta=o.checkpoint_delta;
    $("checkpoint-name").textContent=cp?.name||"No trusted checkpoint";
    $("checkpoint-meta").textContent=cp
      ? short(cp.revision_id,12)+" · created by "+cp.created_by
      :"Create a PASS checkpoint to establish long-range trust.";
    $("checkpoint-state").textContent=cp?(o.checkpoint_tree_matches?"TREE MATCH":"DIVERGED"):"NO CHECKPOINT";
    $("checkpoint-state").className="mini-badge "+(cp&&o.checkpoint_tree_matches?"clean":"");
    $("delta-added").textContent=delta?.added_tools?.length||0;
    $("delta-modified").textContent=delta?.modified_tools?.length||0;
    $("delta-removed").textContent=delta?.removed_tools?.length||0;
    $("delta-tree").textContent=cp?(o.checkpoint_tree_matches?"match":"drift"):"—";
    const chips=[];
    (delta?.added_tools||[]).slice(0,4).forEach(x=>chips.push('<span class="change-chip add">+ '+escapeHtml(x)+'</span>'));
    (delta?.modified_tools||[]).slice(0,4).forEach(x=>chips.push('<span class="change-chip mod">~ '+escapeHtml(x.tool_name)+'</span>'));
    (delta?.removed_tools||[]).slice(0,3).forEach(x=>chips.push('<span class="change-chip del">− '+escapeHtml(x)+'</span>'));
    $("checkpoint-changes").innerHTML=chips.join("")||'<span class="change-chip">No checkpoint divergence</span>';
  }

  function renderTrust(o) {
    const trust=o.trusted_status||{};
    const good=trust.unchanged_trusted_tools?.length||0;
    const mod=trust.modified_from_trusted?.length||0;
    const untrusted=trust.untrusted_tools?.length||0;
    const total=Math.max(1,good+mod+untrusted+(trust.missing_trusted_tools?.length||0));
    $("trusted-count").textContent=good;
    $("modified-count").textContent=mod;
    $("untrusted-count").textContent=untrusted;
    $("trusted-bar").style.width=(good/total*100)+"%";
    $("modified-bar").style.width=(mod/total*100)+"%";
    $("untrusted-bar").style.width=(untrusted/total*100)+"%";

    const watched=[
      ...(trust.modified_from_trusted||[]).map(x=>x.tool_name),
      ...(trust.untrusted_tools||[])
    ];
    $("tool-watchlist").innerHTML=watched.slice(0,6).map(x=>'<span class="watch-item">'+escapeHtml(x)+'</span>').join("")
      ||'<span class="change-chip">No watchlist items</span>';
  }

  function checkForRevision(id) {
    return state.checks.find(x=>x.revision_id===id);
  }

  function revisionDelta(revision,index) {
    const view=state.views.get(revision.revision_id);
    if (view?.parent_delta) return view.parent_delta;
    const next=state.revisions[index+1];
    if (!next) return {added_tools:revision.tools?.map(t=>t.name)||[],removed_tools:[],modified_tools:[]};
    const currentNames=new Set((revision.tools||[]).map(t=>t.name));
    const prevNames=new Set((next.tools||[]).map(t=>t.name));
    return {
      added_tools:[...currentNames].filter(x=>!prevNames.has(x)),
      removed_tools:[...prevNames].filter(x=>!currentNames.has(x)),
      modified_tools:[]
    };
  }

  function renderRevisions() {
    const query=$("revision-search").value.trim().toLowerCase();
    const list=state.revisions.filter(r=>{
      if (!query) return true;
      return r.revision_id.toLowerCase().includes(query) ||
        (r.origin?.channel||"").toLowerCase().includes(query) ||
        (r.origin?.trigger||"").toLowerCase().includes(query) ||
        (r.tools||[]).some(t=>t.name.toLowerCase().includes(query));
    });
    $("revision-count").textContent=list.length+" revision"+(list.length===1?"":"s");

    $("revision-list").innerHTML=list.map((r,i)=>{
      const actualIndex=state.revisions.indexOf(r);
      const check=checkForRevision(r.revision_id);
      const sec=check?.state||"unknown";
      const delta=revisionDelta(r,actualIndex);
      const selected=r.revision_id===state.selectedRevision?" selected":"";
      return '<button class="revision-row'+selected+'" data-revision="'+escapeHtml(r.revision_id)+'">'+
        '<span class="revision-id"><span class="commit-node"></span><span><code>'+short(r.revision_id,10)+'</code><span class="revision-sub">tree '+short(r.tree_hash,8)+'</span></span></span>'+
        '<span class="origin-cell">'+escapeHtml(humanOrigin(r.origin))+'</span>'+
        '<span class="security-pill '+escapeHtml(sec)+'">'+escapeHtml(sec.replaceAll("_"," "))+'</span>'+
        '<span class="change-counts"><span class="plus">+'+(delta.added_tools?.length||0)+'</span><span class="mod">~'+(delta.modified_tools?.length||0)+'</span><span class="minus">−'+(delta.removed_tools?.length||0)+'</span></span>'+
        '<span class="time-cell">'+relativeTime(r.observed_at)+'</span>'+
      '</button>';
    }).join("") || '<div class="inspector-empty"><p>No matching revisions.</p></div>';

    document.querySelectorAll("[data-revision]").forEach(el=>{
      el.addEventListener("click",()=>openRevision(el.dataset.revision));
    });
  }

  function eventIcon(kind) {
    return ({revision:"⑂",security_check:"✓",catalog_signal:"!",review:"◎",checkpoint:"◇"}[kind]||"·");
  }
  function renderTimeline() {
    $("activity-timeline").innerHTML=(state.timeline||[]).slice(0,14).map(e=>{
      const detail=e.revision_id?"rev "+short(e.revision_id,8):(e.details?.reviewer||e.details?.created_by||e.severity||"");
      return '<div class="activity-item '+escapeHtml(e.kind)+'">'+
        '<span class="activity-node">'+eventIcon(e.kind)+'</span>'+
        '<div><div class="activity-summary">'+escapeHtml(e.summary)+'</div><div class="activity-details">'+escapeHtml(detail)+'</div></div>'+
        '<span class="activity-time">'+relativeTime(e.occurred_at)+'</span>'+
      '</div>';
    }).join("") || '<div class="inspector-empty"><p>No activity events yet.</p></div>';
  }

  async function openRevision(id) {
    state.selectedRevision=id;
    renderRevisions();
    document.getElementById("app-shell").classList.add("inspector-open");
    $("inspector-empty").classList.add("hidden");
    $("inspector-content").classList.remove("hidden");

    let data=state.views.get(id);
    if (!data && !state.demo) {
      try {
        data=await fetchJson("/v1/servers/"+encodeURIComponent(state.server)+"/revisions/"+encodeURIComponent(id)+"/view");
        state.views.set(id,data);
      } catch(error) {
        showToast("Could not load revision detail.","error");
        return;
      }
    }
    if (!data) return;
    renderInspector(data);
  }

  function renderInspector(viewData) {
    const r=viewData.revision;
    const check=viewData.security_check;
    const sec=check?.state||"unknown";
    $("inspector-title").textContent="Revision "+short(r.revision_id,8);
    const badge=$("inspector-state");
    badge.className="status-badge "+securityClass(sec);
    badge.textContent=sec.replaceAll("_"," ").toUpperCase();
    $("inspector-origin").textContent=humanOrigin(r.origin);
    $("inspector-revision").textContent=r.revision_id;
    $("inspector-tree").textContent=r.tree_hash;
    $("inspector-time").textContent=formatTime(r.observed_at);
    renderInspectorDiff(viewData.parent_delta);
    renderInspectorSecurity(check);
  }

  function renderInspectorDiff(delta) {
    if (!delta) {
      $("inspector-diff").innerHTML='<div class="change-chip">Initial discovery revision</div>';
      return;
    }
    const blocks=[];
    (delta.added_tools||[]).forEach(name=>blocks.push(
      '<div class="diff-tool"><div class="diff-tool-head"><span>'+escapeHtml(name)+'</span><span class="change-chip add">added</span></div></div>'
    ));
    (delta.modified_tools||[]).forEach(tool=>{
      const paths=(tool.field_changes||[]).map(f=>
        '<div class="diff-path '+escapeHtml(f.kind)+'"><span class="diff-sign">'+(f.kind==="added"?"+":f.kind==="removed"?"−":"~")+'</span><span>'+escapeHtml(f.path)+'</span></div>'
      ).join("") || '<div class="diff-path modified"><span class="diff-sign">~</span><span>canonical definition changed</span></div>';
      blocks.push('<div class="diff-tool"><div class="diff-tool-head"><span>'+escapeHtml(tool.tool_name)+'</span><span class="change-chip mod">modified</span></div>'+paths+'</div>');
    });
    (delta.removed_tools||[]).forEach(name=>blocks.push(
      '<div class="diff-tool"><div class="diff-tool-head"><span>'+escapeHtml(name)+'</span><span class="change-chip del">removed</span></div></div>'
    ));
    $("inspector-diff").innerHTML=blocks.join("")||'<div class="change-chip">No content changes</div>';
  }

  function renderInspectorSecurity(check) {
    if (!check) {
      $("inspector-security").innerHTML='<div class="activity-details">No persisted security check for this revision.</div>';
      return;
    }
    const risk=maxRisk(check);
    $("inspector-security").innerHTML=
      '<div class="security-summary"><div><span class="eyebrow">policy</span><div style="margin-top:3px">'+escapeHtml(check.policy_name)+'</div></div><strong class="mono">'+risk.toFixed(1)+'</strong></div>'+
      '<div class="risk-meter"><span style="width:'+Math.min(100,risk)+'%"></span></div>'+
      '<div class="security-tools">'+(check.tools||[]).map(t=>
        '<div class="security-tool"><span>'+escapeHtml(t.tool_name)+'</span><span>'+escapeHtml(t.change_class||"—")+' · '+(t.risk_score??0).toFixed(1)+'</span></div>'
      ).join("")+'</div>';
  }

  function connectEvents() {
    disconnectEvents();
    if (state.demo || typeof EventSource==="undefined") {
      setLive(state.demo?"demo":"connected");
      return;
    }
    const url="/v1/servers/"+encodeURIComponent(state.server)+"/events";
    const source=new EventSource(url);
    state.source=source;
    source.onopen=()=>setLive("connected");
    source.onerror=()=>setLive("reconnecting");
    source.onmessage=(event)=>consumeEvent(event);
    ["revision","security_check","catalog_signal","review","checkpoint"].forEach(kind=>{
      source.addEventListener(kind,consumeEvent);
    });
  }
  function consumeEvent(event) {
    try {
      const payload=JSON.parse(event.data);
      if (!state.timeline.some(x=>x.event_id===payload.event_id)) {
        state.timeline.unshift(payload);
        renderTimeline();
      }
      if (["revision","security_check","catalog_signal","checkpoint"].includes(payload.kind)) {
        clearTimeout(consumeEvent.refreshTimer);
        consumeEvent.refreshTimer=setTimeout(()=>loadAll(),450);
      }
    } catch (_) {
      setLive("reconnecting");
    }
  }
  function disconnectEvents() {
    if (state.source) state.source.close();
    state.source=null;
  }

  function setLive(mode) {
    const el=$("live-state");
    const text=$("live-state-text");
    el.classList.toggle("disconnected",["disconnected","reconnecting"].includes(mode));
    text.textContent=({connected:"Live",connecting:"Connecting",reconnecting:"Reconnecting",disconnected:"Offline",demo:"Demo live"}[mode]||mode);
  }

  function showToast(message,type="") {
    const el=document.createElement("div");
    el.className="toast "+type;
    el.textContent=message;
    $("toast-region").appendChild(el);
    setTimeout(()=>el.remove(),3200);
  }

  function renderEmptyServer() {
    $("hero-copy").textContent="No DriftGuard revision history exists for this server yet. Intercept tools/list traffic to create the first revision.";
    $("metric-tools").textContent="0";
    $("metric-drift").textContent="0";
    $("metric-ahead").textContent="—";
    $("metric-risk").textContent="0";
    renderRiskDial(0);
    if ($("revision-trajectory")) $("revision-trajectory").innerHTML='<div class="inspector-empty"><p>No risk history yet.</p></div>';
    if ($("surface-map")) $("surface-map").innerHTML='<div class="inspector-empty"><p>No tool surface yet.</p></div>';
    $("revision-list").innerHTML='<div class="inspector-empty"><p>No revisions yet.</p></div>';
    $("activity-timeline").innerHTML='<div class="inspector-empty"><p>No activity yet.</p></div>';
  }

  function bind() {
    $("refresh-button").addEventListener("click",()=>loadAll());
    $("server-input").addEventListener("keydown",(e)=>{
      if (e.key==="Enter") {
        state.server=e.currentTarget.value.trim();
        disconnectEvents();
        loadAll();
      }
    });
    $("revision-search").addEventListener("input",renderRevisions);
    $("inspector-close").addEventListener("click",()=>{
      $("app-shell").classList.remove("inspector-open");
      state.selectedRevision=null;
      renderRevisions();
    });
    $("mobile-menu").addEventListener("click",()=>document.body.classList.toggle("nav-open"));
    document.querySelectorAll(".nav-item").forEach(link=>link.addEventListener("click",()=>{
      document.body.classList.remove("nav-open");
      document.querySelectorAll(".nav-item").forEach(x=>x.classList.remove("active"));
      link.classList.add("active");
    }));
    document.querySelectorAll("[data-scroll]").forEach(btn=>btn.addEventListener("click",()=>{
      document.getElementById(btn.dataset.scroll)?.scrollIntoView({behavior:"smooth"});
    }));
    $("command-button").addEventListener("click",()=>{$("revision-search").focus();$("revision-search").select();});
    document.addEventListener("keydown",(e)=>{
      if ((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==="k") {
        e.preventDefault();$("revision-search").focus();$("revision-search").select();
      }
      if (e.key==="Escape") {
        $("app-shell").classList.remove("inspector-open");
        document.body.classList.remove("nav-open");
      }
    });
  }

  bind();
  loadAll();
})();
