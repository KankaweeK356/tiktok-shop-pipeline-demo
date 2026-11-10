/* Interactive, static Decision Dashboard. All finance/model metrics come from JSON report. */
(function () {
  "use strict";
  const $ = s => document.querySelector(s);
  const state = { data:null, evidence:null, evidenceLayer:"source", evidenceTable:"", neonStatus:"not_loaded", neonTables:[], neonTable:"", neonData:null, neonError:"", neonRunStatus:null, neonArtifactType:"ALL", labStage:0, labTable:"Fact_Orders", labResults:{}, labBusy:false, labError:"", labLog:[], realReady:false, realConfigChecked:false, realLabPhase:"UNKNOWN", realLabCycle:null, realLabOrders:null, realBatch:"initial", realStageIndex:0, realPreviousRunId:"", realRunId:null, realStatus:"", realUrl:"", realError:"", realStartedAt:"", realAdminKey:"", realEvidence:null, autoBatch:"", batchResults:{initial:{},incremental:{}}, resetStatus:"", resetSince:"", resetUrl:"", resetError:"", savedLabManifest:null, savedLabReceipt:null, savedLabSelected:"", savedLabLoading:false, pipelineTab:"flow", notebookBatch:"initial", notebookStage:"ingest", warehouseStatus:"not_loaded", warehouseSnapshot:null, warehouseError:"", warehouseTable:"Fact_Sales_Order_Item", labNeon:null, labNeonTable:null, labNeonBusy:false, labNeonError:"", errorCase:"N01", errorReplayed:false, errorLabOpen:false, view:"business", month:"", group:"ALL", sku:"", skuSort:"lowest_margin", model:"", week:"", replay:false, rows:[] };
  state.batchRun={batch:"",status:"",since:"",runId:null,url:"",stages:[]};
  state.batchRunIds={initial:null,incremental:null};
  state.batchResume={batch:"",runId:null};
  state.selectedResultTable="";
  state.recentRuns=[];state.historyRun=null;state.historyBusy=false;
  state.errorRun={status:"",since:"",url:"",runId:null,phase:"",previous:"0",
    failEvidence:null,fixEvidence:null,error:"",neonRows:null};
  const names = {
    business:["ภาพรวมธุรกิจ","ข้อมูลจาก Warehouse ของ Lab รอบปัจจุบัน · ว่างเมื่อเคลียร์ Lab","ภาพรวมธุรกิจ"],
    pipeline:["Test Pipeline","จาก Source ผ่าน Database และ Data Lake สู่ Warehouse","Test Pipeline"],
    ml:["วางแผนยอดขายและกำไร","เลือกแผน ดู KPI และเปิดดูหลักฐาน ML","วางแผนยอดขายและกำไร"]
  };
  const groups=["PG01","PG02","PG03","PG04","PG05"];
  const money = (n,digits=0) => n===null||n===undefined||!Number.isFinite(Number(n)) ? "—" :
    new Intl.NumberFormat("th-TH",{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(Number(n));
  const pct=(n,digits=1)=> n===null||n===undefined?"—":money(n,digits)+"%";
  const node=(tag,cls="",label=null)=>{
    const el=document.createElement(tag);
    if(cls)el.className=cls;
    if(label!==null)el.textContent=String(label);
    return el;
  };
  function add(parent,...children){for(const c of children)if(c)parent.append(c);return parent;}
  function box(cls,...children){return add(node("div",cls),...children);}
  function link(text,url){
    const a=node("a","source-link",text+" ↗");a.href=url;a.target="_blank";a.rel="noopener noreferrer";return a;
  }
  function small(text,cls="muted"){return node("div","small "+cls,text);}
  function notice(text,warn=false){return box("notice "+(warn?"notice-warning":"notice-info"),node("span","",warn?"⚠":"ⓘ"),node("span","",text));}
  function metric(label,value,description,kind=""){
    return box("metric",node("div","metric-label",label),node("div","metric-value "+kind,value),node("div","metric-sub",description||""));
  }
  function panel(title,description,content,action=null){
    const head=box("panel-head",box("",node("h2","panel-heading",title),description?node("p","panel-description",description):null),action);
    return box("panel",head,content);
  }
  function contentArea(...children){return box("panel-body",...children);}
  function statusLabel(x){
    const good=["PASS","SUCCESS","COMPLETE","READY"].includes(x);
    const bad=["FAIL","INCOMPLETE","INCOMPLETE_COST"].includes(x);
    return node("span","status "+(good?"status-pass":bad?"status-fail":"status-pending"),x||"UNKNOWN");
  }
  function dataTable(columns,rows,formats={}){
    if(!rows || !rows.length)return box("empty-state",node("span","", "ไม่มีข้อมูลในตัวกรองนี้ (ไม่เติมตัวเลขสมมติ)"));
    const table=node("table");
    const thead=node("thead"),hr=node("tr");
    columns.forEach(([key,label])=>add(hr,node("th",formats[key]?.align||"",label)));
    thead.append(hr);table.append(thead);
    const tbody=node("tbody");
    rows.forEach(row=>{
      const tr=node("tr");
      columns.forEach(([key])=>{
        const spec=formats[key]||{};
        const td=node("td",spec.align||"");
        if(spec.kind==="status")td.append(statusLabel(row[key]));
        else if(spec.kind==="risk"){
          const code=row[key],bad=["RISK","GROUP_BELOW"].includes(code);
          td.append(node("span","status "+(bad?"status-fail":code==="GROUP_ABOVE"?"status-pass":"status-pending"),
            code==="RISK"?"เสี่ยงต่ำกว่าเป้า":code==="CHECK"?"รอต้นทุนกลุ่ม":
            code==="GROUP_BELOW"?"ต่ำกว่าเกณฑ์ร้าน":code==="GROUP_ABOVE"?"ถึงเกณฑ์ร้าน":"ข้อมูลไม่พอ"));
        }
        else if(spec.kind==="money")td.textContent=money(row[key],spec.digits||0);
        else if(spec.kind==="percent")td.textContent=pct(row[key],spec.digits===undefined?1:spec.digits);
        else td.textContent=row[key]===null||row[key]===undefined?"—":String(row[key]);
        tr.append(td);
      });
      tbody.append(tr);
    });
    table.append(tbody);
    return box("table-wrap",table);
  }
  function barChart(data,active=""){
    const list=node("div","bar-list"),max=Math.max(1,...data.map(x=>Number(x.value)||0));
    data.forEach(x=>{
      const track=node("div","bar-track"),fill=node("div","bar-fill"+(x.name===active?" bar-active":""));
      fill.style.width=Math.max(0,Math.min(100,(Number(x.value)||0)/max*100))+"%";
      track.append(fill);
      list.append(box("bar-entry",node("div","bar-title",x.name),track,node("div","bar-value",x.display||money(x.value))));
    });
    return list;
  }
  const title=id=>{
    const group=state.data?.business.groups.find(x=>x.product_group_id===id);
    return group?.product_group_name?id+" · "+group.product_group_name:id;
  };
  function labelInput(labelText,type,value,min,max){
    const label=node("label","field"),title=node("span","",labelText);
    const field=node("input");field.type=type;field.value=value;field.min=min;field.max=max;field.step="0.5";
    add(label,title,field);return {label,field};
  }
  function chooseField(labelText,options,current,handler){
    const label=node("label","field"),select=node("select");
    options.forEach(([id,text])=>{
      const opt=node("option","",text);opt.value=id;
      if(id===current)opt.selected=true;
      select.append(opt);
    });
    select.addEventListener("change",()=>handler(select.value));
    add(label,node("span","",labelText),select);
    return label;
  }

  function fashionThumb(){
    const image=node("img","fashion-preview");
    image.src="./assets/womens-top.svg";
    image.alt="ภาพประกอบเสื้อผู้หญิง ไม่ใช่ภาพสินค้าจริง";
    image.loading="lazy";
    return image;
  }

  async function loadWarehouseDashboard(){
    if(state.warehouseStatus==="loading")return;
    state.warehouseStatus="loading";state.warehouseSnapshot=null;state.warehouseError="";
    if(state.view==="business"||state.view==="ml")render();
    try{
      const statusResponse=await fetch("/api/lab-batch",{cache:"no-store"});
      const status=await statusResponse.json();
      if(!statusResponse.ok||!status.ready)throw Error(status.error||"อ่านสถานะ Warehouse ไม่ได้");
      if(status.running){
        state.warehouseSnapshot={...status,running:true};
      }else if(status.phase==="EMPTY"){
        state.warehouseSnapshot={...status,result:null};
      }else{
        if(!status.current_run_id)throw Error("ไม่พบ Run ปัจจุบันที่เชื่อมกับ Warehouse");
        const resultResponse=await fetch("/api/lab-batch-result?run_id="+
          encodeURIComponent(status.current_run_id),{cache:"no-store"});
        const payload=await resultResponse.json();
        if(!resultResponse.ok||!payload.result)throw Error(payload.error||"อ่านผล Warehouse ไม่ได้");
        if(Number(payload.result.cycle)!==Number(status.cycle))
          throw Error("ผล Warehouse ไม่ตรงกับรอบ Lab ปัจจุบัน");
        state.warehouseSnapshot={...status,result:payload.result};
      }
      state.warehouseStatus="ready";
    }catch(error){
      state.warehouseStatus="error";
      state.warehouseSnapshot=null;
      state.warehouseError=error.message||"อ่านข้อมูล Warehouse ไม่ได้";
    }
    if(state.view==="business"||state.view==="ml")render();
  }

  function renderBusiness(){
    const root=$("#app");root.replaceChildren();state.rows=[];
    const snapshot=state.warehouseSnapshot;
    const phase=snapshot?.phase||"UNKNOWN";
    $("#headerMode").textContent=state.warehouseStatus==="ready"?
      phase==="EMPTY"?"Warehouse ว่าง":snapshot?.running?"Warehouse กำลังอัปเดต":"Warehouse · ข้อมูลรอบปัจจุบัน":
      "กำลังตรวจ Warehouse";
    const executed=snapshot?.result?.stages?.find(x=>x.stage==="load")?.evidence?.executed_at;
    $("#snapshotStamp").textContent=executed?
      new Intl.DateTimeFormat("th-TH",{timeZone:"Asia/Bangkok",year:"numeric",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"})
        .format(new Date(executed)):
      snapshot?.cycle?"รอบ Lab "+snapshot.cycle:"—";
    $("#footerStatus").textContent=state.warehouseStatus==="ready"?
      phase==="EMPTY"?"Warehouse ว่าง · ยังไม่มี Run ในรอบนี้":
      snapshot?.running?"กำลังประมวลผล · จะเปิดข้อมูลเมื่อ Run สำเร็จ":
      (snapshot?.result?.batch==="incremental"?"Run 2":"Run 1")+" · Lab รอบ "+(snapshot?.cycle??"—"):
      "ตรวจสอบ Warehouse";
    root.append(notice("หน้านี้อ่านผลจาก DuckDB Warehouse ของ Run ปัจจุบันโดยตรง · เมื่อเคลียร์ Lab สถานะจะกลับเป็นว่างและซ่อนผลรอบก่อน",false));
    if(state.warehouseStatus==="not_loaded"||state.warehouseStatus==="loading"){
      root.append(small("กำลังตรวจสถานะ Lab และ Warehouse…"));return;
    }
    if(state.warehouseStatus==="error"){
      root.append(notice("ไม่สามารถยืนยันข้อมูล Warehouse ได้ จึงไม่แสดงตัวเลขเก่า · "+state.warehouseError,true));
      const retry=node("button","button button-outline","ตรวจสถานะอีกครั้ง");
      retry.type="button";retry.addEventListener("click",loadWarehouseDashboard);root.append(retry);return;
    }
    if(snapshot?.running){
      root.append(node("h2","lab-heading","กำลังประมวลผลข้อมูลเข้า Warehouse"));
      root.append(small("เมื่อ Run สำเร็จ Dashboard จะแสดงข้อมูลรอบนี้ · ระหว่างนี้จะไม่แสดงตัวเลขจากรอบก่อน"));
      return;
    }
    if(phase==="EMPTY"||!snapshot?.result){
      root.append(node("h2","lab-heading","Warehouse ยังไม่มีข้อมูล"));
      root.append(small("Lab รอบ "+(snapshot?.cycle??"—")+" ว่างอยู่ · กด Run 1 ใน Test Pipeline เพื่อสร้างข้อมูล Warehouse รอบใหม่"));
      const open=node("button","button button-primary","ไปที่ Test Pipeline");
      open.type="button";open.addEventListener("click",()=>setView("pipeline"));root.append(open);return;
    }
    const result=snapshot.result;
    const load=result.stages?.find(x=>x.stage==="load")?.evidence?.output;
    if(!load||load.origin!=="NEW_DUCKDB_WAREHOUSE"){
      root.append(notice("Run ปัจจุบันไม่มีหลักฐาน Warehouse ที่ตรวจสอบได้ · ไม่แสดง Snapshot เก่า",true));return;
    }
    const tables=Array.isArray(load.tables)?load.tables:[];
    const previews=load.table_previews||{};
    const names=tables.map(x=>x.name);
    if(!names.length){root.append(notice("Run นี้ยังไม่มีตารางใน Warehouse"));return;}
    if(!names.includes(state.warehouseTable))state.warehouseTable=
      names.includes("Fact_Sales_Order_Item")?"Fact_Sales_Order_Item":names[0];
    const rows=Array.isArray(previews[state.warehouseTable])?previews[state.warehouseTable]:[];
    state.rows=rows;
    const runLabel=result.batch==="incremental"?"Run 2":"Run 1";
    root.append(small("ข้อมูลชุดปัจจุบัน · "+runLabel+" · Lab รอบ "+snapshot.cycle));
    root.append(add(box("metrics"),
      metric("ออเดอร์",money(result.orders_after),"ข้อมูลจาก Run ปัจจุบัน"),
      metric("รายการขาย",money(result.paid_sales_rows),"Fact_Sales_Order_Item"),
      metric("ยอดขายสุทธิ",result.net_revenue===null?"—":"฿"+money(result.net_revenue),"ผลตรวจของ Run นี้")));
    root.append(panel("ตารางใน Warehouse",money(tables.length)+" ตาราง · จำนวนแถวจาก DuckDB Warehouse รอบปัจจุบัน",
      contentArea(dataTable([["name","ชื่อตาราง"],["rows","จำนวนแถว"]],tables))));
    root.append(chooseField("เลือกตารางเพื่อดูแถวตัวอย่าง",
      tables.map(item=>[item.name,item.name+" · "+money(item.rows)+" แถว"]),
      state.warehouseTable,value=>{state.warehouseTable=value;renderBusiness();}));
    root.append(panel("ตัวอย่างแถวจริงจาก Warehouse",state.warehouseTable+" · แสดงได้สูงสุด 5 แถว",
      contentArea(rows.length?
        dataTable(Object.keys(rows[0]).slice(0,10).map(key=>[key,key]),rows):
        notice("ตารางนี้ยังไม่มีแถวข้อมูล"))));
    const refresh=node("button","button button-outline","รีเฟรชข้อมูล Warehouse");
    refresh.type="button";refresh.addEventListener("click",loadWarehouseDashboard);
    root.append(refresh);
  }

  function renderScenario(root){
    const d=state.data;
    const panelBody=node("div","panel-body");
    panelBody.append(notice("Sandbox นี้เปลี่ยนตัวเลขแผนได้ แต่ไม่มีโมเดล Causal/Counterfactual ที่รองรับการคำนวณยอดขายหรือ ROI จากการปรับ Ads และส่วนลด",true));
    const choices=chooseField("Product Group",groups.map(id=>[id,title(id)]),state.group==="ALL"?"PG01":state.group,()=>reset());
    const ads=labelInput("Planned Ads ต่อสัปดาห์ (บาท)","number","0","0","1000000");
    const discount=labelInput("ส่วนลด Campaign เฉลี่ย (%)","number","0","0","100");
    const grid=box("scenario-grid",choices,ads.label,discount.label);
    const summary=node("strong","", "—"),explanation=small("เป็นเพียงการเปรียบเทียบแผน ไม่ใช่การพยากรณ์ยอดขายหรือกำไร"),resetButton=node("button","button button-outline","รีเซ็ตค่า");
    resetButton.type="button";
    const result=box("scenario-results",box("",small("แผนอ้างอิงสัปดาห์ "+d.scenario.reference_week),summary,explanation),resetButton);
    const ref=()=>d.scenario.reference_plans.find(x=>x.product_group_id===choices.querySelector("select").value);
    function update(){
      const value=Number(ads.field.value),disc=Number(discount.field.value);
      if(ads.field.value===""||discount.field.value===""||!Number.isFinite(value)||value<0||!Number.isFinite(disc)||disc<0||disc>100){
        summary.textContent="กรุณากรอกงบ ≥0 และส่วนลด 0–100%";return;
      }
      const difference=value-Number(ref()?.planned_ads_week||0);
      summary.textContent="งบ ฿"+money(value)+" ("+(difference>=0?"+":"")+money(difference)+" จากแผนเดิม) · ส่วนลด "+pct(disc);
    }
    function reset(){
      ads.field.value=Number(ref()?.planned_ads_week||0).toFixed(0);
      discount.field.value=(Number(ref()?.planned_discount_mean_week||0)*100).toFixed(1);
      update();
    }
    choices.querySelector("select").addEventListener("change",reset);
    ads.field.addEventListener("input",update);discount.field.addEventListener("input",update);
    resetButton.addEventListener("click",reset);
    add(panelBody,grid,result);
    root.append(panel("ทดลองวางแผนการตลาด","ทดลองกรอกแผนได้ แต่ยังไม่ได้รัน Scenario Forecast",panelBody));
    reset();
  }

  function renderEvidenceExplorer(root){
    const evidence=state.evidence;
    if(!evidence){
      root.append(panel("สำรวจตารางและไฟล์ของแต่ละชั้นข้อมูล",
        "ยังไม่มีไฟล์หลักฐานของการรันที่ส่งออกในชุดข้อมูลนี้",
        contentArea(notice("รายชื่อตารางและข้อมูลตัวอย่างจะปรากฏเมื่อ GitHub Actions สร้าง classroom_evidence.json สำเร็จ"))));
      return;
    }
    const labels={source:"ฐานข้อมูลต้นทาง (SQLite)",landing:"Data Lake — Landing",
      raw:"Data Lake — Raw",standardized:"Data Lake — Standardized",
      warehouse:"Data Warehouse (DuckDB)",governance:"Governance",control:"Control"};
    if(!evidence.layers[state.evidenceLayer])state.evidenceLayer="source";
    const list=evidence.layers[state.evidenceLayer]||[];
    const options=Object.entries(labels).map(([key,label])=>
      [key,label+" · "+(evidence.layers[key]||[]).length+" รายการ"]);
    const layerSelect=chooseField("เลือกชั้นข้อมูล",options,state.evidenceLayer,v=>{
      state.evidenceLayer=v;state.evidenceTable="";renderPipeline();
    });
    if(!list.some(x=>x.name===state.evidenceTable))
      state.evidenceTable=list[0]?.name||"";
    const datasetSelect=chooseField("เลือกตาราง/ชุดข้อมูล",
      list.map(x=>[x.name,x.name+(x.batch?" · "+x.batch:"")]),
      state.evidenceTable,v=>{state.evidenceTable=v;renderPipeline()});
    const item=list.find(x=>x.name===state.evidenceTable)||list[0];
    const details=item?box("scenario-results",box("",
      small("รูปแบบ: "+item.type+(item.batch?" · รอบ "+item.batch:"")),
      node("strong","",item.name),
      small("จำนวนรายการ: "+(item.records===undefined?"—":money(item.records))+
        " · คอลัมน์: "+(item.columns?.length??"—")),
      small("ตำแหน่งข้อมูล: "+(item.path||"Query จากฐานข้อมูลชั่วคราวใน Runner"))
    )):small("ไม่พบรายการข้อมูลในชั้นนี้");
    const headers=(item?.columns||[]).slice(0,8).map(key=>[key,key]);
    const preview=item?.preview?.length?dataTable(headers,item.preview):small("ไม่มีแถวตัวอย่างหรือเป็นไฟล์ Metadata");
    root.append(panel("สำรวจตารางและไฟล์ของแต่ละชั้นข้อมูล",
      "ดูชื่อชุดข้อมูล โครงสร้างคอลัมน์ และตัวอย่างข้อมูลจากผลรันจริง (Snapshot ไม่ใช่ข้อมูลสด)",
      contentArea(notice("หลักฐานนี้มาจาก SQLite / Parquet / DuckDB ของ GitHub Actions ยังไม่ใช่การ Query Neon โดยตรง",true),
        box("two-col",layerSelect,datasetSelect),details,preview,
        box("h-stack",
          link("ตรวจ Workflow และดาวน์โหลดหลักฐาน","https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/actions/workflows/decision-dashboard-ci.yml"),
          link("เปิด Neon Console (ต้องมีสิทธิ์)","https://console.neon.tech/app/projects")),
        small("โปรเจกต์ Neon demo-pipeline ยังแยกจาก Snapshot นี้ · อย่าตีความว่าข้อมูลตรงกันจนกว่าจะเชื่อมและตรวจยอดจริง"))));
  }

  async function loadNeonEvidence(table=""){
    if(state.neonStatus==="loading")return;
    state.neonStatus="loading";state.neonError="";
    if(state.view==="pipeline")renderPipeline();
    try {
      const url="/api/neon-evidence"+(table?"?table="+encodeURIComponent(table)+"&limit=10":"");
      const response=await fetch(url,{cache:"no-store"});
      const payload=await response.json();
      if(!response.ok || !payload.connected || payload.origin!=="NEON_LIVE")
        throw Error(payload.error || "ยังไม่สามารถอ่าน Neon ได้");
      if(!table){
        state.neonTables=payload.tables;
        state.neonData=null;
        state.neonTable="";
        try {
          const statusResponse=await fetch("/api/neon-status",{cache:"no-store"});
          const live=await statusResponse.json();
          if(statusResponse.ok&&live.connected&&live.origin==="NEON_LIVE")
            state.neonRunStatus=live;
        }catch(_error){state.neonRunStatus=null;}

      }else{
        state.neonData=payload;
        state.neonTable=table;
      }
      state.neonStatus="ready";
    }catch(error){
      state.neonStatus="error";
      state.neonError=error.message||"ไม่สามารถติดต่อฐานข้อมูลได้";
    }
    if(state.view==="pipeline")renderPipeline();
  }

  function renderNeonExplorer(root){
    const wrap=contentArea();
    wrap.append(notice("ข้อมูลส่วนนี้อ่านจาก Neon Branch demo-pipeline โดยตรง ผ่าน API แบบอ่านอย่างเดียว ไม่ใช่ Snapshot ของ GitHub Actions"));
    if(state.neonStatus==="loading"){
      wrap.append(small("กำลังตรวจสอบฐานข้อมูล Neon…"));
    }else if(state.neonStatus==="error"){
      wrap.append(notice("ยังเชื่อม Neon ไม่สำเร็จ: "+state.neonError,true));
    }else if(state.neonStatus==="not_loaded"){
      wrap.append(small("กดตรวจสอบเพื่ออ่านรายชื่อตารางจริงจาก Neon"));
    }else{
      wrap.append(small("เชื่อมต่อได้ · Schema demo_er1 · "+state.neonTables.length+" ตาราง · ข้อมูลจำลอง"));
      const live=state.neonRunStatus;
      if(live?.state){
        const phase=live.state.phase;
        const translated={EMPTY:"ยังไม่มีข้อมูลการทดสอบ",RUN1_READY:"Run 1 ผ่านแล้ว",
          RUN2_READY:"Run 2 ผ่านแล้ว · พร้อมตรวจผล"};
        wrap.append(box("pipeline-meta",
          small("สถานะจริง: "+(translated[phase]||phase)),
          small("รอบข้อมูล: "+live.state.cycle_number),
          small("ออเดอร์ใน Neon: "+money(live.counts.orders)),
          small("รายการสินค้า: "+money(live.counts.order_items)),
          small("หลักฐานไฟล์ที่ลงทะเบียน: "+money(live.counts.artifacts))));
        if(live.runs?.length){
          const rows=live.runs.slice(0,8).map(row=>({
            run_type:row.run_type,status:row.status,
            evidence_type:row.evidence_type==="HISTORICAL_EVIDENCE_IMPORT"?
              "บันทึกย้อนหลังจากรายงาน GitHub":"บันทึกจากระบบ",
            runner_ref:row.runner_ref||"—"
          }));
          wrap.append(small("ประวัติการประมวลผล (Neon Control)"));
          wrap.append(dataTable([
            ["run_type","การรัน"],["status","ผล"],["evidence_type","ที่มาหลักฐาน"]
          ],rows));
        }
        if(live.counts.artifacts===0)
          wrap.append(notice("ยังไม่มีไฟล์ Data Lake ที่ลงทะเบียนในพื้นที่จัดเก็บถาวร · ประวัติ Run บันทึกแล้ว แต่ยังต้องเก็บไฟล์ Parquet/คลังข้อมูล",true));
        const files=live.archived_files||[];
        if(files.length){
          const types=["ALL",...new Set(files.map(f=>f.artifact_type))];
          if(!types.includes(state.neonArtifactType))state.neonArtifactType="ALL";
          wrap.append(chooseField("เลือกประเภทไฟล์หลักฐาน",types.map(t=>
            [t,t==="ALL"?"ทุกประเภท":t]),state.neonArtifactType,v=>{
              state.neonArtifactType=v;renderPipeline();
            }));
          const filtered=files.filter(f=>state.neonArtifactType==="ALL"||
            f.artifact_type===state.neonArtifactType);
          const shown=filtered.map(f=>({
            artifact_type:f.artifact_type,
            filename:(f.artifact_uri||"").split("/").pop(),
            bytes:f.size_bytes,
            stage:f.stage_name
          }));
          wrap.append(dataTable([
            ["artifact_type","ประเภทไฟล์"],["filename","ชื่อไฟล์"],
            ["stage","ขั้นตอน"],["bytes","ขนาด (Bytes)"]
          ],shown));
          wrap.append(small("เป็นรายการหลักฐานจาก Neon Control · พื้นที่เก็บไฟล์เป็น Private และตรวจว่ามีไฟล์จริงแล้ว"));
        }
      }

      if(state.neonTables.length){
        wrap.append(chooseField("เลือกตารางใน Neon",
          [["","— เลือกตาราง —"],...state.neonTables.map(t=>[t,t])],
          state.neonTable, name=>{if(name)loadNeonEvidence(name);}));
      }
      const d=state.neonData;
      if(d?.table){
        wrap.append(box("pipeline-meta",
          small("ตาราง: "+d.table),
          small("จำนวน Records: "+money(d.row_count)),
          small("เวลา Query: "+(d.generated_at||"—"))));
        wrap.append(small("โครงสร้างตาราง ("+d.columns.length+" คอลัมน์)"));
        wrap.append(dataTable([["column_name","ชื่อคอลัมน์"],["data_type","ชนิดข้อมูล"]],d.columns.slice(0,35)));
        wrap.append(small("ตัวอย่างข้อมูลสูงสุด "+d.preview_limit+" รายการ"));
        const cols=d.columns.slice(0,8).map(x=>[x.column_name,x.column_name]);
        wrap.append(d.preview_rows.length?dataTable(cols,d.preview_rows):
          small("ตารางนี้ยังไม่มีข้อมูลจริงใน Neon · ขณะนี้ยังไม่ได้รัน Cloud Pipeline"));
      }
    }
    const button=node("button","button button-outline","↻ ตรวจสอบ Neon อีกครั้ง");
    button.type="button";button.disabled=state.neonStatus==="loading";
    button.addEventListener("click",()=>loadNeonEvidence());
    wrap.append(button);
    wrap.append(link("เปิด Neon Console เพื่อตรวจเอง (ต้องมีสิทธิ์)","https://console.neon.tech/app/projects"));
    root.append(panel("เปิดข้อมูลจริงจาก Neon PostgreSQL",
      "โครงสร้างตาราง ตัวอย่างข้อมูล และจำนวนรายการที่ Query จากฐานข้อมูล ณ ขณะนั้น",wrap));
  }

  // Educational step runner. Only read-only queries / archive verification are authorized.
  // A real new ETL cycle needs a separate authenticated GitHub Actions dispatcher.
  const LAB_STEPS=[
    {id:"ingest",title:"Ingest",path:"CSV → Neon PostgreSQL",
      why:"ตรวจว่าข้อมูลต้นทางถูกนำเข้าครบ และแสดงตัวอย่างแถวจริงจากฐานข้อมูล",
      input:"ER1 Source Database + ตารางที่เลือก",process:"ตรวจ 25 ตาราง / Schema / จำนวนแถว",
      output:"Neon table rows + ตัวอย่าง 5 รายการ",
      note:"ตรวจผลของการนำเข้าเดิม ไม่ได้ INSERT ข้อมูลใหม่"},
    {id:"extract",title:"Extract",path:"Neon → Private Raw Parquet",
      why:"เปิดไฟล์ Raw Parquet จาก Object Storage แล้วเทียบกับข้อมูลใน Neon",
      input:"Neon Source + Parquet ใน Private Bucket",process:"อ่าน Parquet metadata และตรวจจำนวน Records",
      output:"จำนวน Rows + ตารางข้อมูล Raw ตัวอย่าง",
      note:"ตรวจ Snapshot ที่จัดเก็บ ไม่สร้างไฟล์ใหม่"},
    {id:"transform",title:"Transform",path:"Raw → Standardized",
      why:"เห็นความแตกต่างก่อนและหลังแปลงรายการออเดอร์เป็นรายการขายที่ชำระแล้ว",
      input:"Raw Fact_Order_Items",process:"อ่าน Standardized และเทียบ Paid Items จาก Neon",
      output:"Before / After + จำนวนรายการเปรียบเทียบ",
      note:"เล่นซ้ำหลักฐาน Transform เดิม ไม่คำนวณหรือเขียน Parquet ใหม่"},
    {id:"load",title:"Load",path:"Standardized → DuckDB Warehouse",
      why:"ยืนยันว่าไฟล์ Warehouse มีอยู่จริงและผลโหลด Sales Fact ตรงกับข้อมูลก่อนโหลด",
      input:"Standardized Sales Fact",process:"ตรวจไฟล์ DuckDB จริงและผล Load ใน Validation Report",
      output:"ขนาดไฟล์ Warehouse และจำนวน Sales Fact",
      note:"ไม่ได้ Query ตาราง DuckDB ใหม่; ใช้รายงานยืนยันผลจากงานที่ผ่านแล้ว"},
    {id:"validate",title:"Validate",path:"Neon ↔ Warehouse",
      why:"คำนวณ Paid Items และ Net Revenue จาก Neon อีกครั้งเพื่อเทียบ Warehouse",
      input:"ข้อมูล Neon ปัจจุบัน + Warehouse Validation Report",
      process:"SQL Reconciliation + Compare counts + Compare Net Revenue",
      output:"PASS/FAIL ของยอดและจำนวนรายการ + Gap",
      note:"เป็นการตรวจยอดใหม่ ไม่ใช่ ETL ใหม่"}
  ];

  async function runLabStage(){
    const index=state.labStage;
    if(state.labBusy||index>0&&!state.labResults[LAB_STEPS[index-1].id]?.success)return;
    const def=LAB_STEPS[index];
    state.labBusy=true;state.labError="";
    const started=Date.now();
    state.labLog=[{at:new Date().toISOString(),stage:def.title,detail:"เริ่มตรวจหลักฐาน",result:"RUNNING"},...state.labLog].slice(0,14);
    renderPipeline();
    try{
      const args=new URLSearchParams({stage:def.id});
      if(index<2)args.set("table",state.labTable);
      const response=await fetch("/api/lab-step?"+args.toString(),{cache:"no-store"});
      const payload=await response.json();
      if(!response.ok)throw Error(payload.error||"HTTP "+response.status);
      if(payload.mode!=="READ_ONLY_EVIDENCE_REPLAY"||
         payload.classification!=="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK")
        throw Error("ผลรันไม่ได้ระบุที่มาของหลักฐานอย่างถูกต้อง");
      state.labResults[def.id]=payload;
      if(!payload.success){
        state.labError="พบผลตรวจ FAIL ใน Step นี้ ดูรายการที่ไม่ผ่านแล้วกด Retry ได้";
        state.labLog.unshift({at:payload.executed_at,stage:def.title,
          detail:payload.checks.filter(x=>!x.pass).map(x=>x.label).join(" · "),result:"FAIL"});
        state.rows=payload.output?.preview||[];
        state.labBusy=false;state.labLog=state.labLog.filter(x=>x.result!=="RUNNING").slice(0,14);
        renderPipeline();return;
      }
      state.labLog.unshift({at:payload.executed_at,stage:def.title,
        detail:"ตรวจจริงจาก Neon / Private Storage · "+Math.round(Date.now()-started)+" ms",
        result:"PASS"});
      state.rows=payload.output?.preview||[];
    }catch(e){
      state.labError=e.message||"ไม่สามารถตรวจหลักฐานได้";
      state.labLog.unshift({at:new Date().toISOString(),stage:def.title,
        detail:state.labError,result:"ERROR"});
    }
    state.labBusy=false;
    state.labLog=state.labLog.filter(x=>x.result!=="RUNNING").slice(0,14);
    renderPipeline();
  }

  function renderLabResult(result){
    if(!result)return box("lab-placeholder",
      node("span","lab-placeholder-icon","▷"),
      node("strong","","ยังไม่ตรวจ Step นี้"),
      small("กดตรวจหลักฐาน เพื่อให้ Server อ่าน Neon และไฟล์เก็บถาวรโดยไม่ประมวลผล ETL ใหม่"));
    const wrap=box("lab-result");
    wrap.append(box("lab-meta",
      statusLabel(result.success?"PASS":"FAIL"),
      small("ตรวจล่าสุด "+new Intl.DateTimeFormat("th-TH",{timeZone:"Asia/Bangkok",
        hour:"2-digit",minute:"2-digit",second:"2-digit"}).format(new Date(result.executed_at))),
      small(result.mode==="REAL_GITHUB_ACTIONS_STAGE"?
        "ผลจาก GitHub Worker ที่ประมวลผลใหม่":"อ้างอิง GitHub Run #"+result.historical_run)));
    if(result.metrics?.length){
      wrap.append(box("lab-metrics",...result.metrics.map(m=>
        box("lab-stat",small(m.label),
          node("strong","",typeof m.value==="number"?money(m.value,m.unit==="THB"?2:0):String(m.value)),
          small(m.unit||"")))));
    }
    const summary=box("lab-checks");
    result.checks.forEach(item=>summary.append(box("lab-check",
      node("span","lab-check-icon "+(item.pass?"lab-ok":"lab-fail"),item.pass?"✓":"!"),
      small(item.label),statusLabel(item.pass?"PASS":"FAIL"))));
    wrap.append(summary);
    const input=result.input;
    if(input?.files?.length)wrap.append(small("ไฟล์ Source ที่อ่านจริง: "+input.files.length+" ไฟล์"));
    if(input?.preview?.length){
      const columns=Object.keys(input.preview[0]).slice(0,6).map(key=>[key,key]);
      wrap.append(node("h3","lab-subheading","Input · ตัวอย่างก่อนประมวลผล"),
        dataTable(columns,input.preview));
    }
    if(result.output?.preview?.length){
      const columns=Object.keys(result.output.preview[0]).slice(0,7).map(key=>[key,key]);
      wrap.append(node("h3","lab-subheading",
        "Output · ตัวอย่างผลลัพธ์จาก "+(result.output.origin||"หลักฐานจริง")),
        dataTable(columns,result.output.preview));
    }else if(result.output?.note){
      wrap.append(notice(result.output.note,true));
    }
    if(result.output?.tables?.length){
      wrap.append(node("h3","lab-subheading","ตารางและจำนวนข้อมูลที่เกิดขึ้นในขั้นนี้"));
      const previews=result.output.table_previews||{};
      const table=node("table"),head=node("thead"),headRow=node("tr");
      headRow.append(node("th","","ตาราง / ไฟล์"),node("th","","จำนวนแถว"));
      head.append(headRow);table.append(head);
      const body=node("tbody");
      result.output.tables.forEach(item=>{
        const row=node("tr"),cell=node("td");
        if(Object.prototype.hasOwnProperty.call(previews,item.name)){
          const button=node("button","table-name-button",item.name+" · ดูข้อมูล");
          button.type="button";
          button.addEventListener("click",()=>{
            const selected=result.batch+"/"+result.stage+"/"+item.name;
            state.selectedResultTable=state.selectedResultTable===selected?"":selected;
            renderPipeline();
          });
          cell.append(button);
        }else cell.textContent=item.name;
        row.append(cell,node("td","",money(item.rows)));body.append(row);
      });
      table.append(body);wrap.append(box("table-wrap",table));
      const selectedName=state.selectedResultTable.startsWith(result.batch+"/"+result.stage+"/")?
        state.selectedResultTable.split("/").slice(2).join("/"):"";
      if(selectedName&&Object.prototype.hasOwnProperty.call(previews,selectedName)){
        const rows=previews[selectedName];
        wrap.append(node("h3","lab-subheading",selectedName+" · ตัวอย่างสูงสุด 5 แถว"));
        wrap.append(rows.length?dataTable(Object.keys(rows[0]).map(key=>[key,key]),rows):
          small("ตารางนี้ยังไม่มีข้อมูล"));
        wrap.append(small("— หมายถึงไม่มีค่า · คอลัมน์ _KEY เป็นรหัสอ้างอิง ไม่ใช่จำนวน"));
      }else if(!Object.keys(previews).length)wrap.append(small(
        "ผลรันเก่านี้เก็บจำนวนแถวไว้ แต่ไม่ได้เก็บตัวอย่างทุกตาราง · Run ใหม่จะคลิกดูได้"));
    }
    if(result.output?.file){
      wrap.append(small("ไฟล์หลักฐาน: "+result.output.file.split("/").pop()));
    }
    wrap.append(node("div","lab-provenance",
      "ชนิดผลลัพธ์: "+result.provenance+
      (result.mode==="REAL_GITHUB_ACTIONS_STAGE"?" · REAL PYTHON ETL EXECUTION":" · READ-ONLY EVIDENCE REPLAY")));
    return wrap;
  }

  function renderErrorRecoveryLab(root){
    const details=node("details","lab-reference");
    details.open=state.errorLabOpen;
    details.addEventListener("toggle",()=>{state.errorLabOpen=details.open;});
    details.append(node("summary","","Error Recovery Lab · 6 กรณี (เปิดดูผล Fail → Fix → Retry)"));
    const body=box("lab-reference-body");
    body.append(notice("ส่วนนี้ Replay หลักฐานการทดสอบ Error จาก Python/SQLite Runner ที่ผ่านแล้ว ไม่ได้ฉีด Error ลง Neon ที่มี 900 ออเดอร์",true));
    const errors=state.evidence?.error_recovery_evidence||[];
    const labels={
      E01:"E01 · SKU FK ไม่ถูกต้อง",
      E02:"E02 · ขาดไฟล์ Source",
      T01:"T01 · Voucher Rule ผิด",
      T02:"T02 · Campaign ทับซ้อน",
      L01:"L01 · Rollback เมื่อโหลดผิดพลาด",
      L02:"L02 · Replay ไม่เพิ่มยอดซ้ำ"
    };
    if(!errors.length){
      body.append(small("ยังไม่มีไฟล์ผลทดสอบ Error Suite จาก GitHub CI · เมื่อ Workflow ทดสอบครบ 6 กรณีจะปรากฏผลที่นี่"));
    }else{
      if(!errors.some(x=>x.case===state.errorCase))state.errorCase=errors[0].case;
      body.append(chooseField("เลือกกรณีผิดพลาด",errors.map(x=>[x.case,labels[x.case]||x.case]),
        state.errorCase,v=>{state.errorCase=v;state.errorReplayed=false;renderPipeline();}));
      const run=node("button","button button-outline","▷ Replay ผลทดสอบ Error + Retry");
      run.type="button";run.addEventListener("click",()=>{state.errorReplayed=true;renderPipeline();});
      body.append(run);
      if(state.errorReplayed){
        const c=errors.find(x=>x.case===state.errorCase);
        const detail=(state.evidence.error_case_details||[]).find(x=>x.case_id===state.errorCase);
        body.append(box("lab-metrics",
          box("lab-stat",small("Detect"),node("strong","",String(c.detected||"—"))),
          box("lab-stat",small("Retry from"),node("strong","",c.retry_from||"ไม่มี (Replay สำเร็จ)")),
          box("lab-stat",small("Result"),statusLabel(c.passed?"PASS":"FAIL"))));
        body.append(dataTable([["stage","ขั้นตอน"],["before","ก่อนแก้"],["after","หลัง Retry"],
          ["expected","ผลที่คาดหวัง"]],[c]));
        if(detail?.stage_events?.length){
          const events=detail.stage_events.slice(-12).map(e=>({
            stage:e.stage||"—",status:e.status||"—",code:e.error_code||"—",
            date:e.at||"—"
          }));
          body.append(node("h3","lab-subheading","Stage Log จากการทดสอบจริง"),
            dataTable([["stage","Step"],["status","ผล"],["code","Error Code"],
              ["date","บันทึกเวลา"]],events));
        }
        if(detail?.detected_error)
          body.append(small("หลักฐานตอนตรวจพบ: "+String(detail.detected_error.error_code||"—")+
            " / "+String(detail.detected_error.stage||"—")));
      }
    }
    details.append(body);root.append(details);
  }

  async function loadRealCapabilities(){
    try{
      const response=await fetch("/api/lab-batch",{cache:"no-store"});
      const data=await response.json();
      state.realReady=response.ok&&data.ready===true;
      state.realLabPhase=data.phase||"UNKNOWN";
      state.realLabCycle=data.cycle??null;
      state.realLabOrders=data.orders??null;
      if(data.previous_run_id)state.batchRunIds.initial=data.previous_run_id;
      state.batchResume={batch:data.resume_batch||"",runId:data.resume_run_id||null};
      state.recentRuns=data.history||[];
    }catch(_error){state.realReady=false;}
    state.realConfigChecked=true;
    if(state.view==="pipeline")renderPipeline();
  }

  async function dispatchRealStep(){
    if(!state.realReady||state.labBusy||state.realStatus==="queued"||
       state.realStatus==="in_progress")return;
    const stage=LAB_STEPS[state.realStageIndex]?.id,batch=state.realBatch;
    const prior=state.realStageIndex===0&&batch==="initial"?"0":
      String(state.realPreviousRunId||"").trim();
    if(!/^(0|[1-9][0-9]{0,18})$/.test(prior)||prior==="0"&&
       !(batch==="initial"&&state.realStageIndex===0)){
      state.realError="กรุณาใส่ GitHub Run ID ของขั้นที่ผ่านก่อนหน้า";
      state.autoBatch="";
      renderPipeline();return;
    }
    state.realError="";state.realStatus="submitting";
    renderPipeline();
    try{
      const response=await fetch("/api/lab-dispatch",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({stage,batch,previous_run_id:prior})
      });
      const result=await response.json();
      if(!response.ok||!result.accepted)
        throw Error(result.error||"GitHub ไม่รับคำสั่งรัน");
      state.realStartedAt=new Date().toISOString();
      state.realStatus="queued";state.realUrl=result.workflow_url;
      state.realRunId=null;
      renderPipeline();
      window.setTimeout(checkRealRun,4000);
    }catch(error){
      state.realStatus="failure";state.realError=error.message||"สั่งรันไม่ได้";
      state.autoBatch="";
      renderPipeline();
    }
  }

  async function checkRealRun(){
    if(!state.realReady||!state.realStartedAt)return;
    const stage=LAB_STEPS[state.realStageIndex]?.id,batch=state.realBatch;
    const prior=state.realStageIndex===0&&batch==="initial"?"0":
      state.realPreviousRunId;
    try{
      const url="/api/lab-dispatch?"+new URLSearchParams({
        stage,batch,previous_run_id:String(prior),since:state.realStartedAt
      });
      const response=await fetch(url,{cache:"no-store"});
      const data=await response.json();
      if(!response.ok)throw Error(data.error||"ติดตามงานไม่ได้");
      if(data.found){
        state.realRunId=data.run_id;state.realStatus=data.status;
        state.realUrl=data.url;
        if(data.status==="completed"){
          state.realStatus=data.conclusion==="success"?"success":"failure";
          if(state.realStatus==="success"){
            state.realPreviousRunId=String(data.run_id);
            try{
              const evidenceResponse=await fetch("/api/lab-real-result?run_id="+encodeURIComponent(data.run_id),{
                cache:"no-store"});
              const receipt=await evidenceResponse.json();
              if(evidenceResponse.ok&&receipt.mode==="REAL_GITHUB_ACTIONS_STAGE")
                state.realEvidence=receipt.receipt;
              else state.realError=receipt.error||"ไม่สามารถอ่าน Output จาก Worker";
            }catch(err){state.realError=err.message||"อ่าน Artifact ไม่สำเร็จ";}
            if(!state.realEvidence)state.autoBatch="";
          }
          if(state.realStatus==="failure")state.autoBatch="";
        }
      }
      if(state.realStatus==="success"&&state.realEvidence){
        state.batchResults[batch][stage]={evidence:state.realEvidence,url:state.realUrl,
          runId:data.run_id};
      }
      renderPipeline();
      if(["queued","in_progress"].includes(state.realStatus))
        window.setTimeout(checkRealRun,4000);
      if(state.autoBatch===batch&&state.realStatus==="success"&&state.realEvidence){
        if(state.realStageIndex<LAB_STEPS.length-1){
          state.realStageIndex++;state.notebookStage=LAB_STEPS[state.realStageIndex].id;
          state.realStatus="";state.realEvidence=null;state.realStartedAt="";
          window.setTimeout(dispatchRealStep,500);
        }else state.autoBatch="";
      }
      if(state.realStatus==="success"&&stage==="validate")loadRealCapabilities();
    }catch(error){state.realError=error.message||"ไม่สามารถตรวจสถานะได้";
      state.autoBatch="";renderPipeline();}
  }

  function renderRealRunner(root){
    const content=box("lab-reference-body");
    content.append(notice("รันใน Neon Branch classroom-step-lab แยกจาก demo-pipeline ที่มี 900 ออเดอร์ และจาก Analytics · ส่งต่อ Checkpoint/Workspace ผ่าน GitHub Artifact"));
    if(!state.realConfigChecked)content.append(small("กำลังตรวจสิทธิ์การสั่งงาน…"));
    else if(!state.realReady)content.append(notice(
      "ระบบสั่งรันยังไม่พร้อม กรุณาตรวจการเชื่อม GitHub และ Neon ของ Lab",true));
    const phase=state.realLabPhase;
    const expected=state.realBatch==="initial"?"EMPTY":"RUN1_READY";
    if(phase!==expected)content.append(notice(
      "Neon ปัจจุบันเป็น "+(phase||"ไม่ทราบสถานะ")+
      " · การรัน "+state.realBatch+" ต้องอยู่ในสถานะ "+expected+
      " เท่านั้น ไม่ Reset หรือเขียนทับข้อมูลใดโดยอัตโนมัติ",true));
    content.append(small("Neon Lab Status: "+phase+" · ออเดอร์ในพื้นที่ทดลอง: "+money(state.realLabOrders)));
    content.append(box("two-col",
      chooseField("เลือก Batch",
        [["initial","Run 1 · Initial"],["incremental","Run 2 · Incremental"]],
        state.realBatch,v=>{state.realBatch=v;state.realStageIndex=0;
          state.realStatus="";state.realStartedAt="";state.realRunId=null;state.realEvidence=null;
          state.realPreviousRunId="";renderPipeline();}),
      chooseField("ขั้นตอนที่จะประมวลผล",
        LAB_STEPS.map((step,i)=>[String(i),String(i+1)+". "+step.title]),
        String(state.realStageIndex),v=>{state.realStageIndex=Number(v);
          state.realStatus="";state.realStartedAt="";state.realRunId=null;
          renderPipeline();})));
    if(!(state.realBatch==="initial"&&state.realStageIndex===0)){
      const field=node("label","field");
      const input=node("input");input.type="text";
      input.placeholder="Run ID ของ Step ที่เสร็จแล้ว";input.value=state.realPreviousRunId;
      input.addEventListener("input",()=>{state.realPreviousRunId=input.value.trim();});
      field.append(node("span","","GitHub Run ID ก่อนหน้า"),input);
      content.append(field);
    }
    content.append(small("ก่อนรัน: "+LAB_STEPS[state.realStageIndex].input+
      " · หลังรัน: "+LAB_STEPS[state.realStageIndex].output));
    const controls=box("lab-actions");
    const run=node("button","button button-primary","▶ Execute Real ETL Step");
    run.type="button";run.disabled=!state.realReady||phase!==expected||
      ["queued","in_progress","submitting"].includes(state.realStatus);
    run.addEventListener("click",dispatchRealStep);controls.append(run);
    if(state.realStartedAt){
      const refresh=node("button","button button-outline","↻ เช็ก GitHub Run");
      refresh.type="button";refresh.addEventListener("click",checkRealRun);
      controls.append(refresh);
    }
    if(state.realStatus==="success"&&state.realStageIndex<4){
      const next=node("button","button button-outline","เลือก Step ถัดไป →");
      next.type="button";next.addEventListener("click",()=>{
        state.realStageIndex++;state.realStatus="";state.realStartedAt="";
        state.realRunId=null;state.realEvidence=null;renderPipeline();
      });controls.append(next);
    }
    content.append(controls);
    if(state.realEvidence&&state.realStatus==="success"){
      content.append(node("h3","lab-subheading","ผลรันจริง · Input / Output จาก GitHub Worker"));
      content.append(renderLabResult(state.realEvidence));
    }
    if(state.realError)content.append(notice(state.realError,true));
    if(state.realStatus)content.append(box("pipeline-meta",
      small("GitHub status: "+state.realStatus),
      small("GitHub Run ID: "+(state.realRunId||"กำลังจัดคิว")),
      small("Step ผ่านได้เมื่อ GitHub workflow conclusion = success เท่านั้น")));
    if(state.realUrl)content.append(link("เปิด GitHub Actions และดู Log",state.realUrl));
    content.append(small("Worker ใช้ Workflow: classroom-real-step.yml · ไม่สั่ง Reset และไม่แตะ Analytics"));
    root.append(panel("รัน ETL จริง · ทีละขั้น",
      "แยกจากการตรวจหลักฐานย้อนหลัง • ต้องมีสิทธิ์ผู้ควบคุมและสถานะ Neon ที่ถูกต้อง",
      content));
  }

  async function loadSavedLabEvidence(){
    try{
      const response=await fetch("./data/lab_manifest.json",{cache:"no-cache"});
      if(response.ok){
        const manifest=await response.json();
        if(manifest.schema_version==="real_lab_steps_v1" &&
           manifest.data_classification==="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK")
          state.savedLabManifest=manifest;
      }
    }catch(_error){/* No completed real step snapshots yet. */}
    if(state.view==="pipeline")renderPipeline();
  }

  async function selectSavedLabStage(item){
    state.savedLabSelected=item.batch+"/"+item.stage;
    state.savedLabLoading=true;renderPipeline();
    try{
      const result=await fetch(item.file,{cache:"no-cache"});
      if(!result.ok)throw Error("HTTP "+result.status);
      const data=await result.json();
      if(data.evidence?.mode!=="REAL_GITHUB_ACTIONS_STAGE" ||
         data.source_type!=="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK" ||
         data.batch!==item.batch||data.stage!==item.stage)
        throw Error("Provenance ของผลรันไม่ถูกต้อง");
      state.savedLabReceipt=data;
    }catch(error){
      state.savedLabReceipt=null;
      state.labError="ไม่สามารถอ่านตัวอย่างจาก GitHub Run จริงได้: "+error.message;
    }
    state.savedLabLoading=false;renderPipeline();
  }

  function renderSavedLab(root){
    const manifest=state.savedLabManifest;
    const body=contentArea();
    body.append(notice("ผลส่วนนี้มาจากการรัน Python + Neon จริงใน GitHub Actions คนละ Job พร้อมตัวอย่างแถวที่ Worker บันทึกไว้ ไม่ใช่การสร้าง ETL ใหม่เมื่อคลิกดู"));
    if(!manifest?.runs?.length){
      body.append(small("ยังไม่มีผล Step ที่เผยแพร่เป็น Data Snapshot จาก GitHub Worker"));
    }else{
      const options=box("lab-steps");
      manifest.runs.forEach(entry=>{
        const selected=state.savedLabSelected===entry.batch+"/"+entry.stage;
        const btn=node("button","lab-step"+(selected?" lab-active":""));
        btn.type="button";btn.disabled=state.savedLabLoading;
        btn.append(node("span","lab-step-number",
          String(LAB_STEPS.findIndex(x=>x.id===entry.stage)+1).padStart(2,"0")),
          box("lab-step-text",
            node("strong","",(entry.batch==="initial"?"Initial":"Incremental")+" · "+
              (LAB_STEPS.find(x=>x.id===entry.stage)?.title||entry.stage)),
            small("GitHub Run #"+entry.run_id)),
          node("span","lab-step-state",selected?"กำลังแสดง":"ดูผลจริง"));
        btn.addEventListener("click",()=>selectSavedLabStage(entry));
        options.append(btn);
      });
      body.append(options);
      if(state.savedLabLoading)body.append(small("กำลังโหลดผลลัพธ์จาก Worker…"));
      else if(state.savedLabReceipt && manifest.runs.some(entry=>
          entry.run_id===state.savedLabReceipt.git_run_id))
        body.append(renderLabResult(state.savedLabReceipt.evidence));
      if(state.savedLabReceipt?.git_run_id)
        body.append(link("เปิด Log ของ GitHub Run นี้",
          "https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/actions/runs/"+
          state.savedLabReceipt.git_run_id));
    }
    root.append(panel("ผลประมวลผลจริงทีละ Step · ใช้สาธิตกับอาจารย์",
      "เลือก Step เพื่อดู Input, Output ตัวอย่างแถว และผลตรวจสอบจาก Python Worker จริง",body));
  }

  function renderLegacyPipeline(){
    const root=$("#app");root.replaceChildren();
    const live=state.neonRunStatus;
    const summary=live?.state;
    const hero=box("lab-hero",
      box("lab-hero-main",
        node("span","lab-kicker","INTERACTIVE PIPELINE LAB · SOURCE-BACKED"),
        node("h2","lab-heading","กดตรวจทีละขั้น เห็นข้อมูลก่อนและหลัง"),
        node("p","lab-description",
          "สองโหมดแยกกัน: สั่งรัน ETL จริงแบบทีละขั้น และตรวจหลักฐานเก่าแบบอ่านอย่างเดียว พร้อม Input → Process → Output")),
      box("lab-hero-aside",
        node("span","lab-hero-tag","โหมดปลอดภัย · ตรวจซ้ำหลักฐานจริง"),
        node("strong","",summary?.phase||"กำลังอ่านสถานะ"),
        small(summary?"รอบข้อมูล "+summary.cycle_number+" · "+money(live.counts.orders)+" ออเดอร์":"กำลังเชื่อม Neon")));
    root.append(hero);
    renderSavedLab(root);
    renderRealRunner(root);
    root.append(notice("ส่วนตรวจหลักฐานด้านล่างเป็น Read-only Verification ไม่ใช่ ETL ใหม่; ใช้ Execute Real ETL Step ด้านบนเท่านั้นเมื่อมีสิทธิ์และสถานะฐานข้อมูลพร้อม"));
    root.append(node("h3","lab-subheading","ตรวจหลักฐานจากการรันที่ผ่านมา (Read-only Verification)"));
    const progress=box("lab-steps");
    LAB_STEPS.forEach((def,i)=>{
      const result=state.labResults[def.id];
      const canOpen=i===0||Boolean(state.labResults[LAB_STEPS[i-1].id]?.success);
      const action=node("button","lab-step"+(i===state.labStage?" lab-active":"")+
        (result?.success?" lab-complete":""));
      action.type="button";action.disabled=!canOpen||state.labBusy;
      action.append(
        node("span","lab-step-number",result?.success?"✓":String(i+1).padStart(2,"0")),
        box("lab-step-text",node("strong","",def.title),small(def.path)),
        node("span","lab-step-state",result?.success?"ผ่านแล้ว":canOpen?"เลือกขั้นตอน":"รอขั้นก่อน"));
      action.addEventListener("click",()=>{state.labStage=i;state.labError="";renderPipeline();});
      progress.append(action);
    });
    root.append(progress);
    const def=LAB_STEPS[state.labStage];
    const completed=state.labResults[def.id];
    const unlocked=state.labStage===0||Boolean(state.labResults[LAB_STEPS[state.labStage-1].id]?.success);
    const main=contentArea();
    main.append(node("div","lab-step-caption","STEP "+String(state.labStage+1).padStart(2,"0")+" / 05"),
      node("h3","lab-step-detail-title",def.title+" — "+def.path),
      node("p","lab-description",def.why));
    if(state.labStage<2 && state.neonTables.length){
      const options=state.neonTables.map(x=>[x,x]);
      if(!state.neonTables.includes(state.labTable))state.labTable="Fact_Orders";
      main.append(chooseField("เลือก Source Table ที่ต้องการตรวจ",options,state.labTable,val=>{
        state.labTable=val;
        // Each table is its own evidence check. Change invalidates downstream.
        state.labResults={};state.labStage=0;state.labLog=[];
        renderPipeline();
      }));
    }
    const io=box("lab-io");
    io.append(
      box("lab-io-card",node("span","lab-io-label","01 · INPUT"),node("strong","",def.input)),
      box("lab-io-card",node("span","lab-io-label","02 · PROCESS"),node("strong","",def.process)),
      box("lab-io-card",node("span","lab-io-label","03 · OUTPUT"),node("strong","",def.output)));
    main.append(io,node("p","lab-footnote",def.note));
    const actionRow=box("lab-actions");
    const run=node("button","button button-primary",state.labBusy?"กำลังตรวจข้อมูล…":
      (completed?"↻ ตรวจหลักฐาน Step "+(state.labStage+1)+" อีกครั้ง":"▷ ตรวจหลักฐาน Step "+(state.labStage+1)));
    run.type="button";
    run.disabled=!unlocked||state.labBusy||state.neonStatus!=="ready";
    run.addEventListener("click",runLabStage);
    actionRow.append(run);
    if(completed?.success&&state.labStage<4){
      const next=node("button","button button-outline","Step ถัดไป →");
      next.type="button";next.addEventListener("click",()=>{state.labStage++;renderPipeline();});
      actionRow.append(next);
    }
    main.append(actionRow);
    if(!unlocked)main.append(notice("ต้องตรวจหลักฐาน Step ก่อนหน้าให้ผ่านก่อน",true));
    if(state.neonStatus==="error")main.append(notice(state.neonError||"อ่าน Neon ไม่สำเร็จ",true));
    if(state.labError)main.append(notice(state.labError+" · สามารถตรวจหลักฐาน Step เดิมซ้ำได้",true));
    main.append(node("h3","lab-subheading","ผลการตรวจสอบ"),renderLabResult(completed));
    root.append(panel("ทดลองขั้นตอนที่ "+(state.labStage+1),"ตรวจแหล่งข้อมูลจริงแบบอ่านอย่างเดียว ไม่ใช่การรัน ETL ใหม่",main));
    if(state.labLog.length)root.append(panel("Execution Log ของการทดลองครั้งนี้",
      "กิจกรรมจากการกดในหน้าเว็บ ไม่ใช่ Log ย้อนหลังของ GitHub Worker",
      dataTable([["at","เวลา (UTC)"],["stage","Step"],["result","ผล"],["detail","รายละเอียด"]],
        state.labLog,{result:{kind:"status"}})));
    renderErrorRecoveryLab(root);
    const detail=node("details","lab-reference");
    const trigger=node("summary","","เปิดดู Data Explorer / รายชื่อไฟล์ / หลักฐาน GitHub");
    detail.append(trigger);
    const explorer=box("lab-reference-body");
    renderNeonExplorer(explorer);renderEvidenceExplorer(explorer);
    detail.append(explorer);
    root.append(detail);
    root.append(box("lab-links",
      link("การรัน Neon Pipeline จริงที่ผ่าน GitHub Actions","https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/actions/runs/42487488684"),
      link("หลักฐาน Cloud Storage ที่ตรวจครบ 64 ไฟล์","https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/actions/runs/42488944625")));
    state.rows=completed?.output?.preview||[];
  }

  const NOTEBOOK_STAGES=[
    ["ingest","Source → Database","นำข้อมูลจำลองเข้าฐานข้อมูลต้นทาง และ sync 25 ตารางไป Neon"],
    ["extract","Database → Data Lake","บันทึก Landing และ Raw Parquet จากข้อมูลในฐานข้อมูล"],
    ["transform","Data Lake · จัดรูปข้อมูล","แปลง Raw เป็น Standardized และตรวจเงื่อนไขข้อมูล"],
    ["load","Data Lake → Warehouse","โหลดข้อมูลที่เปลี่ยนไปยัง DuckDB และปรับ Mart"],
    ["validate","ตรวจผลทั้งเส้นทาง","เทียบจำนวนและยอดระหว่างฐานข้อมูลต้นทางกับ Warehouse"]
  ];
  function runWholeBatch(){
    const batch=state.notebookBatch;
    if(state.batchRun.status==="queued"||state.batchRun.status==="in_progress"||
       state.batchRun.status==="submitting")return;
    const previous=state.batchResume.batch===batch&&state.batchResume.runId?
      String(state.batchResume.runId):batch==="initial"?"0":
      String(state.batchRunIds.initial||"");
    if(batch==="incremental"&&!/^[1-9][0-9]{0,18}$/.test(previous)){
      state.realError="Run 2 ต้องรอ Run 1 จบก่อน";renderPipeline();return;
    }
    state.realError="";state.batchRun={batch,status:"submitting",since:"",runId:null,url:"",stages:[]};
    renderPipeline();
    fetch("/api/lab-batch",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({batch,previous_run_id:previous})})
      .then(async response=>{const data=await response.json();
        if(!response.ok||!data.accepted)throw Error(data.error||"สั่ง Run ไม่สำเร็จ");
        state.batchRun.status="queued";state.batchRun.since=new Date().toISOString();
        state.batchRun.url=data.workflow_url;renderPipeline();
        window.setTimeout(checkBatchRun,3000);
      }).catch(error=>{state.batchRun.status="failure";state.realError=error.message;
        renderPipeline();});
  }
  async function checkBatchRun(){
    const current=state.batchRun;
    if(!current.since||!["queued","in_progress"].includes(current.status))return;
    try{
      const query=new URLSearchParams({batch:current.batch,since:current.since});
      const response=await fetch("/api/lab-batch?"+query,{cache:"no-store"});
      const data=await response.json();
      if(!response.ok)throw Error(data.error||"ติดตาม Run ไม่ได้");
      if(data.found){
        current.runId=data.run_id;current.url=data.url;current.stages=data.stages||[];
        current.status=data.status==="completed"?
          (data.conclusion==="success"?"success":"failure"):data.status;
        const active=current.stages.find(x=>x.status==="in_progress");
        const latest=[...current.stages].reverse().find(x=>x.conclusion==="success");
        state.notebookStage=NOTEBOOK_STAGES[active?.index??latest?.index??0][0];
        for(const step of current.stages.filter(x=>x.conclusion==="success")){
          const stage=NOTEBOOK_STAGES[step.index]?.[0];
          if(!stage||state.batchResults[current.batch]?.[stage])continue;
          try{
            const proofResponse=await fetch("/api/lab-batch-result?"+
              new URLSearchParams({run_id:String(current.runId),stage}),{cache:"no-store"});
            if(!proofResponse.ok)continue;
            const proof=await proofResponse.json();
            state.batchResults[current.batch][stage]={evidence:proof.evidence,
              url:current.url,runId:current.runId};
          }catch(_error){/* Stage artifact may still be uploading. */}
        }
      }
      if(current.status==="success"){
        const resultResponse=await fetch("/api/lab-batch-result?run_id="+
          encodeURIComponent(current.runId),{cache:"no-store"});
        const payload=await resultResponse.json();
        if(!resultResponse.ok)throw Error(payload.error||"อ่านผล Run ไม่สำเร็จ");
        current.result=payload.result;
        state.batchRunIds[current.batch]=current.runId;
        state.batchResults[current.batch]=Object.fromEntries(payload.result.stages.map(item=>
          [item.stage,{evidence:item.evidence,url:current.url,runId:current.runId}]));
        state.notebookStage="validate";
        loadRealCapabilities();
      }
      if(current.status==="failure"){
        state.realError="Run ไม่สำเร็จ · เปิด Log เพื่อดูขั้นที่ผิดพลาด แล้วกดรันต่อ";
        state.batchResume={batch:current.batch,runId:current.runId};
        loadRealCapabilities();
      }
      renderPipeline();
      if(["queued","in_progress"].includes(current.status))
        window.setTimeout(checkBatchRun,4000);
    }catch(error){state.realError=error.message;renderPipeline();
      if(["queued","in_progress"].includes(current.status))
        window.setTimeout(checkBatchRun,8000);}
  }
  async function showHistoryRun(runId){
    state.historyBusy=true;state.realError="";renderPipeline();
    try{
      const response=await fetch("/api/lab-batch-result?run_id="+encodeURIComponent(runId),
        {cache:"no-store"});
      const payload=await response.json();
      if(!response.ok)throw Error(payload.error||"อ่านผลรอบก่อนไม่ได้");
      state.historyRun={runId,result:payload.result};
    }catch(error){state.realError=error.message;}
    state.historyBusy=false;renderPipeline();
  }
  async function resetErrorLab(nextCase=state.errorCase){
    state.errorRun.status="submitting";renderPipeline();
    try{
      const response=await fetch("/api/lab-error",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({phase:"reset"})});
      const data=await response.json();
      if(!response.ok||!data.ready)throw Error(data.error||"เตรียม Error Lab ใหม่ไม่ได้");
      state.errorCase=nextCase;
      state.errorRun={status:"",since:"",url:"",runId:null,phase:"",
        previous:"0",failEvidence:null,fixEvidence:null,error:"",neonRows:null};
    }catch(error){state.errorRun.status="failure";state.errorRun.error=error.message;}
    renderPipeline();
  }
  async function startErrorRun(phase="fail"){
    const previous=phase==="fix"?String(state.errorRun.runId||""):"0";
    if(phase==="fail")state.errorRun={status:"",since:"",url:"",runId:null,
      phase:"",previous:"0",failEvidence:null,fixEvidence:null,error:"",neonRows:null};
    state.errorRun.status="submitting";state.errorRun.phase=phase;
    state.errorRun.previous=previous;state.errorRun.error="";
    renderPipeline();
    try{
      const response=await fetch("/api/lab-error",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({case:state.errorCase,phase,previous_run_id:previous})});
      const data=await response.json();
      if(!response.ok||!data.accepted)throw Error(data.error||"เริ่มทดสอบ Error ไม่สำเร็จ");
      state.errorRun.status="queued";state.errorRun.since=new Date().toISOString();
      state.errorRun.url=data.url;renderPipeline();
      window.setTimeout(checkErrorRun,4000);
    }catch(error){state.errorRun.status="failure";state.errorRun.error=error.message;
      renderPipeline();}
  }
  async function checkErrorRun(){
    const current=state.errorRun;
    if(!current.since||!["queued","in_progress"].includes(current.status))return;
    try{
      const response=await fetch("/api/lab-error?"+
        new URLSearchParams({since:current.since,case:state.errorCase,
          phase:current.phase,previous_run_id:current.previous}),{cache:"no-store"});
      const data=await response.json();
      if(!response.ok)throw Error(data.error||"ติดตามการทดสอบไม่ได้");
      current.status=data.status==="completed"?
        (data.conclusion==="success"?"success":"failure"):data.status;
      current.url=data.url||current.url;
      if(data.run_id)current.runId=data.run_id;
      if(data.evidence){
        if(current.phase==="fail")current.failEvidence=data.evidence;
        else {
          current.fixEvidence=data.evidence;
          if(state.errorCase==="N01"){
            fetch("/api/lab-error?table=1",{cache:"no-store"})
              .then(response=>response.json())
              .then(value=>{current.neonRows=value.rows||[];renderPipeline();})
              .catch(()=>{});
          }
        }
      }
      if(current.status==="failure")current.error="การทดสอบไม่ผ่าน · เปิด Log เพื่อตรวจสาเหตุ";
      renderPipeline();
      if(["queued","in_progress"].includes(current.status)||
         current.status==="success"&&
           !(current.phase==="fail"?current.failEvidence:current.fixEvidence))
        window.setTimeout(checkErrorRun,5000);
    }catch(error){current.error=error.message;renderPipeline();
      window.setTimeout(checkErrorRun,8000);}
  }
  async function requestNewCycle(){
    if(!state.realReady||state.realLabPhase!=="RUN2_READY"||!state.realLabCycle)return;
    if(!window.confirm("เคลียร์เฉพาะข้อมูล Lab ทดสอบรอบนี้เพื่อเริ่ม Run 1 ใหม่? ผลรันเก่ายังดูได้"))return;
    const confirmation="RESET-DEMO-DATA";
    state.resetStatus="submitting";state.resetError="";renderPipeline();
    try{
      const response=await fetch("/api/lab-reset",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({confirmation,
          expected_cycle:Number(state.realLabCycle)})});
      const data=await response.json();
      if(!response.ok||!data.accepted)throw Error(data.error||"ส่งคำสั่งเคลียร์ไม่ได้");
      state.resetSince=new Date().toISOString();state.resetUrl=data.workflow_url;
      state.resetStatus="queued";renderPipeline();
      window.setTimeout(checkNewCycle,4000);
    }catch(error){state.resetStatus="";state.resetError=error.message;renderPipeline();}
  }
  async function checkNewCycle(){
    if(!state.resetSince)return;
    try{
      const query=new URLSearchParams({cycle:String(state.realLabCycle),since:state.resetSince});
      const response=await fetch("/api/lab-reset?"+query,{cache:"no-store"});
      const data=await response.json();
      if(!response.ok)throw Error(data.error||"ตรวจสถานะไม่ได้");
      if(data.found){state.resetStatus=data.status==="completed"?
        (data.conclusion==="success"?"success":"failure"):data.status;
        state.resetUrl=data.url||state.resetUrl;}
      if(state.resetStatus==="success"){
        state.realPreviousRunId="";state.realRunId=null;state.realStatus="";
        state.realEvidence=null;state.notebookBatch="initial";state.notebookStage="ingest";
        state.batchResults={initial:{},incremental:{}};
        state.batchRunIds={initial:null,incremental:null};
        state.batchRun={batch:"",status:"",since:"",runId:null,url:"",stages:[]};
        state.labNeon=null;state.labNeonTable=null;loadRealCapabilities();
      }
      renderPipeline();
      if(["queued","in_progress"].includes(state.resetStatus))window.setTimeout(checkNewCycle,4000);
    }catch(error){state.resetError=error.message;renderPipeline();}
  }
  async function loadLabNeon(schema="",table=""){
    if(state.labNeonBusy)return;
    state.labNeonBusy=true;state.labNeonError="";renderPipeline();
    try{
      const query=table?"?"+new URLSearchParams({schema,table}):"";
      const response=await fetch("/api/lab-neon-evidence"+query,{cache:"no-store"});
      const data=await response.json();
      if(!response.ok||!data.connected)throw Error(data.error||"อ่าน Neon ไม่สำเร็จ");
      if(table)state.labNeonTable=data;else state.labNeon=data;
    }catch(error){state.labNeonError=error.message||"อ่าน Neon ไม่สำเร็จ";}
    state.labNeonBusy=false;renderPipeline();
  }
  function renderPipeline(){
    const root=$("#app");root.replaceChildren();
    const tabs=box("notebook-tabs");
    [["flow","ขั้นตอนการรัน"],["neon","Neon · ฐานข้อมูลต้นทาง"],["files","Snapshot เก่า · Data Lake / Warehouse"],
      ["errors","ทดสอบข้อผิดพลาด"]].forEach(([id,label])=>{
      const button=node("button","notebook-tab"+(state.pipelineTab===id?" is-active":""),label);
      button.type="button";button.setAttribute("aria-pressed",String(state.pipelineTab===id));
      button.addEventListener("click",()=>{state.pipelineTab=id;renderPipeline();
        if(id==="neon"&&!state.labNeon)loadLabNeon();});tabs.append(button);
    });
    root.append(tabs);
    if(state.pipelineTab==="neon"){
      root.append(notice("ข้อมูลสดจาก branch classroom-live-run-lab · Database tiktok_demo · อ่านอย่างเดียว"));
      root.append(small("เลือกตาราง Fact_Orders เพื่อดูออเดอร์จริงใน Lab หรือเลือกตารางอื่นเพื่อดูข้อมูลและจำนวนแถว"));
      root.append(link("เปิด Lab ที่กำลังรันใน Neon Console (ต้องมีสิทธิ์)",
        "https://console.neon.tech/app/projects/hidden-leaf-09169842/branches/br-sweet-term-bepzkkrb?database=tiktok_demo"));
      if(state.labNeonBusy)root.append(small("กำลังอ่านรายชื่อตาราง…"));
      if(state.labNeonError)root.append(notice(state.labNeonError,true));
      const tables=state.labNeon?.tables||[];
      if(tables.length){
        root.append(small("demo_er1 · "+tables.filter(x=>x.table_schema==="demo_er1").length+
          " ตารางธุรกิจ | demo_control · "+tables.filter(x=>x.table_schema==="demo_control").length+" ตารางควบคุม"));
        root.append(chooseField("เลือกตารางธุรกิจใน Neon",[["","— เลือกตาราง —"],...tables.filter(x=>x.table_schema==="demo_er1").map(x=>
          [x.table_schema+"."+x.table_name,x.table_schema+" · "+x.table_name])],
          state.labNeonTable?state.labNeonTable.schema+"."+state.labNeonTable.table:"",value=>{
            const [schema,table]=value.split(".");if(table)loadLabNeon(schema,table);
          }));
      }
      if(state.labNeonTable){
        const d=state.labNeonTable;
        root.append(node("h3","lab-subheading",d.schema+"."+d.table+" · "+money(d.row_count)+" แถว"));
        root.append(dataTable([["column_name","คอลัมน์"],["data_type","ชนิดข้อมูล"]],d.columns));
        root.append(node("h3","lab-subheading","ตัวอย่างข้อมูล 5 แถวแรก"));
        root.append(dataTable(d.columns.slice(0,8).map(x=>[x.column_name,x.column_name]),d.preview_rows));
      }return;
    }
    if(state.pipelineTab==="files"){
      root.append(notice("Data Lake เก็บ Landing / Raw / Standardized; DuckDB Warehouse เป็นไฟล์จาก GitHub Worker ไม่ใช่ตารางใน Neon"));
      root.append(small("ผลรันปัจจุบันดูได้ในแท็บ ขั้นตอนการรัน โดยเปิดขั้นแล้วกดชื่อตารางด้านล่าง · ส่วนต่อไปเป็น Snapshot เก่า"));
      renderEvidenceExplorer(root);return;
    }
    if(state.pipelineTab==="errors"){
      const scenarios=[
        ["N01","สินค้าอ้างถึงกลุ่มที่ไม่มีอยู่","Database · Neon จริง"],
        ["E01","รายการสั่งซื้ออ้างถึง SKU ที่ไม่มีอยู่","Source → Database"],
        ["E02","ไฟล์ออเดอร์ต้นทางหาย","Source → Database"],
        ["T01","ข้อมูล Voucher ผิดกฎ","Data Lake → Standardized"],
        ["T02","ช่วงเวลา Campaign ซ้อนกัน","Data Lake → Standardized"],
        ["L01","โหลด Warehouse ไม่สำเร็จ","Data Lake → Warehouse"]
      ];
      const selected=scenarios.find(x=>x[0]===state.errorCase)||scenarios[0];
      const busy=["submitting","queued","in_progress"].includes(state.errorRun.status);
      root.append(node("h2","lab-heading","สาธิตการรับมือเมื่อข้อมูลมีปัญหา"));
      root.append(notice("ใช้ชุดข้อมูลจำลองใน Error Lab ซึ่งแยกจาก Run 1/2 เพื่อให้เห็นว่าระบบพบปัญหาอะไร แก้อย่างไร และผลหลังแก้เป็นอย่างไร",false));
      root.append(chooseField("เลือกกรณี",[...scenarios.map(x=>[x[0],x[1]])],
        state.errorCase,value=>{
          if(busy)return;
          resetErrorLab(value);
        }));
      root.append(node("h3","lab-subheading","สถานการณ์ที่จะทดลอง · "+selected[1]));
      root.append(small("จุดที่ระบบจะตรวจ: "+selected[2]));
      if(state.errorCase==="N01"){
        root.append(small("ตัวอย่างข้อมูล: N01.csv ระบุ Product_Group_ID เป็น MISSING_GROUP ซึ่งไม่มีอยู่ในฐานข้อมูล"));
        root.append(dataTable([["SKU_ID","SKU_ID"],["Product_Group_ID","Product_Group_ID"],
          ["SKU_Name","SKU_Name"]],[{SKU_ID:"ERROR_TEST_SKU",
            Product_Group_ID:"MISSING_GROUP",SKU_Name:"สินค้าเดโมทดสอบ Error"}]));
        root.append(small("กฎใน Neon: SKU ต้องอ้างถึง Product_Group_ID ที่มีอยู่จริง"));
      }else root.append(small("ระบบจะใช้ชุดข้อมูลทดสอบแยกที่จำลองสถานการณ์นี้ แล้วตรวจจนถึงขั้นที่พบปัญหา"));
      if(!state.errorRun.failEvidence){
        const button=node("button","button button-primary",
          busy?"กำลังตรวจชุดข้อมูล…":"▶ เริ่มทดสอบกรณีนี้");
        button.type="button";button.disabled=busy;
        button.addEventListener("click",()=>startErrorRun("fail"));root.append(button);
      }
      if(busy)root.append(small(state.errorRun.phase==="fix"?
        "กำลังแก้ข้อมูลและรันซ้ำ…":"กำลังตรวจชุดข้อมูลและหาจุดที่พบปัญหา…"));
      if(state.errorRun.error)root.append(notice(state.errorRun.error,true));
      if(state.errorRun.failEvidence){
        const found=state.errorRun.failEvidence;
        root.append(node("h3","lab-subheading","1 · ระบบพบปัญหาที่ขั้น "+found.stage));
        root.append(notice("สาเหตุ: "+found.title+" · "+(found.detail.error_message||found.detail.error_code),true));
        if(found.detail.source_rows?.length){
          const rows=found.detail.source_rows;
          root.append(small("ข้อมูลที่ทำให้เกิด Error"));
          root.append(dataTable(Object.keys(rows[0]).map(key=>[key,key]),rows));
        }
        if(found.detail.source_file)root.append(small("Source: "+found.detail.source_file));
        root.append(small("ผลต่อการรัน: ขั้นนี้ไม่ผ่าน ข้อมูลชุดนี้จึงยังไม่ถือว่าผ่าน Pipeline · รหัสอ้างอิง: "+found.detail.error_code));
        root.append(node("h3","lab-subheading","2 · แนวทางแก้"));
        root.append(small(found.fix));
        if(!state.errorRun.fixEvidence){
          const fix=node("button","button button-primary",
            busy?"กำลังแก้ตามแนวทางและตรวจต่อ…":"ให้ระบบแก้ตามแนวทาง แล้วรันต่อ");
          fix.type="button";fix.disabled=busy;
          fix.addEventListener("click",()=>startErrorRun("fix"));root.append(fix);
        }
      }
      if(state.errorRun.fixEvidence){
        const fixed=state.errorRun.fixEvidence.detail;
        root.append(node("h3","lab-subheading","3 · ผลหลังแก้"));
        root.append(small("รันต่อจากขั้นที่พบปัญหา · สถานะหลังแก้: "+fixed.retry_status));
        if(fixed.before&&fixed.after){
          root.append(small("ก่อนแก้"));
          root.append(dataTable(Object.keys(fixed.before).map(key=>[key,key]),[fixed.before]));
          root.append(small("หลังแก้ และบันทึกสำเร็จ"));
        }
        if(fixed.result_rows?.length)
          root.append(dataTable(Object.keys(fixed.result_rows[0]).slice(0,8)
            .map(key=>[key,key]),fixed.result_rows));
        if(state.errorCase==="N01"){
          root.append(small("ข้อมูลจริงใน Neon · classroom-error-lab · demo_er1.Dim_SKU"));
          if(state.errorRun.neonRows?.length)
            root.append(dataTable(Object.keys(state.errorRun.neonRows[0])
              .map(key=>[key,key]),state.errorRun.neonRows));
          root.append(link("เปิด Error Lab ใน Neon Console ↗",
            "https://console.neon.tech/app/projects/hidden-leaf-09169842/branches/br-summer-field-bey5qhdt?database=tiktok_demo"));
          root.append(small('ใน Neon เปิด SQL Editor แล้วดูตาราง demo_er1."Dim_SKU" โดยกรอง SKU_ID=ERROR_TEST_SKU'));
        }
        const again=node("button","button","เริ่มสถานการณ์นี้อีกครั้ง");
        again.type="button";again.addEventListener("click",()=>resetErrorLab());
        root.append(again);
      }
      if(state.errorRun.url)root.append(link("ดูรายละเอียดการรันใน GitHub",state.errorRun.url));
      return;
    }
    if(state.pipelineTab==="operate"){
      root.append(notice("Lab ใหม่เริ่มจากฐานข้อมูลว่าง ข้อมูลต้นทางอยู่ในไฟล์ Source; การกด Run 1 และ Run 2 จะประมวลผลจริงผ่าน GitHub Actions"));
      renderRealRunner(root);return;
    }
    const phase=state.realLabPhase;
    root.append(box("notebook-intro",
      node("h2","lab-heading","Source → Database → Data Lake → Warehouse"),
      node("p","lab-description","แต่ละ Run เดินครบทั้งเส้นทาง Run 2 เติมและอัปเดตข้อมูลต่อจาก Run 1"),
      small("Lab ที่ใช้รัน: "+(phase==="UNKNOWN"?"กำลังตรวจสอบ":phase)+" · "+money(state.realLabOrders||0)+" ออเดอร์")));
    const batchPicker=box("notebook-runs");
    [["initial","Run 1 · ข้อมูลตั้งต้น","800 ออเดอร์"],
      ["incremental","Run 2 · เติมข้อมูลต่อ","800 → 900 ออเดอร์"]].forEach(([id,label,detail])=>{
      const button=node("button","notebook-run"+(state.notebookBatch===id?" is-active":""));
      button.type="button";button.setAttribute("aria-pressed",String(state.notebookBatch===id));
      button.append(node("strong","",label),small(detail));
      button.addEventListener("click",()=>{state.notebookBatch=id;state.notebookStage="ingest";
        state.savedLabReceipt=null;state.savedLabSelected="";renderPipeline();});batchPicker.append(button);
    });root.append(batchPicker);
    const expectedBatchPhase=state.notebookBatch==="initial"?"EMPTY":"RUN1_READY";
    const canStartBatch=state.realReady&&phase===expectedBatchPhase&&
      (state.notebookBatch==="initial"||Boolean(state.batchRunIds.initial));
    const batchBusy=["submitting","queued","in_progress"].includes(state.batchRun.status);
    const batchAction=node("button","button button-primary",batchBusy?
      "กำลังรัน "+(state.batchRun.batch==="initial"?"Run 1":"Run 2")+" ทั้งรอบ…":
      state.batchResume.batch===state.notebookBatch&&state.batchResume.runId?
      "▶ รันต่อจากขั้นที่ผิดพลาด":
      "▶ รัน "+(state.notebookBatch==="initial"?"Run 1":"Run 2")+" ทั้งรอบ");
    batchAction.type="button";batchAction.disabled=!canStartBatch||batchBusy;
    batchAction.addEventListener("click",runWholeBatch);root.append(batchAction);
    if(!canStartBatch)root.append(small(!state.realReady?
      "ระบบสั่งงานยังไม่พร้อม":phase!==expectedBatchPhase?
      "รอบนี้ต้องรอสถานะ Lab "+expectedBatchPhase+" (ตอนนี้ "+phase+")":
      "ต้องให้ Run 1 ผ่านครบก่อน จึงเริ่ม Run 2 ได้"));
    root.append(node("p","notebook-caption","กด Run หนึ่งครั้ง ระบบจะวิ่งครบทุกขั้น แล้วเปิดดูผลของแต่ละขั้นเมื่อเสร็จ"));
    if(state.batchRun.status){
      root.append(small("สถานะ Run: "+state.batchRun.status+
        (state.batchRun.runId?" · GitHub Run #"+state.batchRun.runId:"")));
      if(state.batchRun.url)root.append(link("ดูการทำงานและ Log จริง",state.batchRun.url));
      if(state.realError)root.append(notice(state.realError,true));
    }
    const runState={submitting:"กำลังส่งคำสั่ง",queued:"รอ GitHub เริ่ม",
      in_progress:"กำลังประมวลผล",success:"เสร็จแล้ว",failure:"ไม่สำเร็จ"};
    const entries=state.savedLabManifest?.runs?.filter(x=>x.batch===state.notebookBatch)||[];
    NOTEBOOK_STAGES.forEach(([id,title,description],index)=>{
      const entry=entries.find(x=>x.stage===id),active=state.notebookStage===id;
      const cell=node("section","notebook-cell"+(active?" is-open":""));
      const head=node("button","notebook-cell-head");head.type="button";
      head.setAttribute("aria-expanded",String(active));
      const savedResult=state.batchResults[state.notebookBatch]?.[id];
      const liveStep=state.batchRun.batch===state.notebookBatch?
        state.batchRun.stages.find(x=>x.index===index):null;
      const runningNow=liveStep?.status==="in_progress";
      head.append(node("span","notebook-number",String(index+1)),
        box("notebook-cell-title",node("strong","",title),small(description)),
        node("span","notebook-cell-state",savedResult||liveStep?.conclusion==="success"?
          "ผ่านแล้ว":runningNow?"กำลังรัน":liveStep?.conclusion==="failure"?"ผิดพลาด":"รอรัน"));
      head.addEventListener("click",()=>{
        state.notebookStage=id;state.savedLabReceipt=null;renderPipeline();
      });cell.append(head);
      if(active){
        const body=box("notebook-cell-body");
        body.append(small("Input: "+(index===0?"Source CSV ชุด "+(state.notebookBatch==="initial"?"ตั้งต้น":"ข้อมูลใหม่"):
          index===1?"25 ตารางใน Neon":index===2?"Raw Parquet":index===3?"Standardized Parquet":"Database และ Warehouse")));
        body.append(small("ขั้นนี้ทำอะไร: "+description));
        if(liveStep?.started_at)body.append(small("เริ่ม "+
          new Date(liveStep.started_at).toLocaleTimeString("th-TH")+
          (liveStep.completed_at?" · เสร็จ "+new Date(liveStep.completed_at).toLocaleTimeString("th-TH"):"")));
        if(savedResult)body.append(box("notebook-output",
          node("strong","","ผลจากการรันครั้งนี้"),renderLabResult(savedResult.evidence),
          link("ดู Log ของขั้นนี้",savedResult.url)));
        if(!savedResult)body.append(small(runningNow?"กำลังประมวลผลขั้นนี้จริง":
          "ผลของขั้นนี้จะแสดงเมื่อ Run จบและหลักฐานพร้อม"));
        if(entry){
          const history=node("details","notebook-history");
          history.open=state.savedLabReceipt?.batch===state.notebookBatch&&state.savedLabReceipt?.stage===id;
          history.append(node("summary","","ดูตัวอย่างจาก Lab เดิม (ไม่ใช่ผลรอบนี้)"));
          const historyBody=box("notebook-history-body");
          if(state.savedLabLoading)historyBody.append(small("กำลังอ่านผลรอบก่อน…"));
          else if(state.savedLabReceipt?.batch===state.notebookBatch&&state.savedLabReceipt?.stage===id){
            const receipt=state.savedLabReceipt;
            historyBody.append(renderLabResult(receipt.evidence),
              link("ดู GitHub Run รอบก่อน","https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/actions/runs/"+receipt.git_run_id));
          }else{
            const open=node("button","button button-outline","เปิดหลักฐานเดิม");
            open.type="button";open.addEventListener("click",()=>selectSavedLabStage(entry));historyBody.append(open);
          }
          history.append(historyBody);body.append(history);
        }
        if(id==="ingest"){
          body.append(small("ขั้นนี้ sync ข้อมูลธุรกิจ 25 ตารางเข้า Neon · กดชื่อตารางด้านบนเพื่อดูตัวอย่างจากรันนี้"));
          const neonButton=node("button","button button-outline","ดูตารางและแถวจริงใน Neon");
          neonButton.type="button";
          neonButton.addEventListener("click",()=>{
            const prefix=state.notebookBatch+"/ingest/";
            const selected=state.selectedResultTable.startsWith(prefix)?
              state.selectedResultTable.slice(prefix.length):"Fact_Orders";
            state.pipelineTab="neon";renderPipeline();
            loadLabNeon("demo_er1",selected);
          });
          body.append(neonButton);
        }
        if(id==="extract")body.append(small("การตรวจความครบถ้วนระหว่าง Database กับ Raw ใช้จำนวนตารางและไฟล์ manifest"));
        if(id==="validate")body.append(small("ผลตรวจท้ายรอบเทียบ Paid Items และ Net Revenue ระหว่างฐานข้อมูลต้นทางกับ Warehouse"));
        cell.append(body);
      }
      root.append(cell);
    });
    if(state.batchRun.status==="success"&&state.batchRun.batch===state.notebookBatch){
      const summary=state.batchRun.result;
      const download=node("a","button button-outline","↓ ดาวน์โหลด Warehouse ครบทุกตาราง (ZIP/CSV)");
      download.href="/api/lab-batch-result?download=warehouse&run_id="+encodeURIComponent(state.batchRun.runId);
      root.append(box("lab-result",node("h3","lab-subheading","สรุปผล Run นี้"),
        small("ผ่านครบ 5 ขั้น · ใช้เวลา "+money(summary?.elapsed_seconds,1)+" วินาที"),
        small("ออเดอร์ก่อนรัน "+money(summary?.orders_before)+" → หลังรัน "+
          money(summary?.orders_after)+" · เพิ่ม "+money(summary?.orders_added)),
        small("รายการขายใน Warehouse "+money(summary?.paid_sales_rows)+" แถว"),
        small(summary?.no_duplicate_sales_items?"ตรวจแล้ว: ไม่มีรายการขายซ้ำ":"ยังไม่มีผลตรวจรายการซ้ำ"),
        small("กดเปิดแต่ละขั้นด้านบนเพื่อดูตารางและตัวอย่างข้อมูลจริง"),download));
    }
    root.append(notice("ข้อมูลต้นทางแยกอยู่ใน Source; เมื่อ Run 2 จบแล้ว จึงเคลียร์เฉพาะ Lab นี้ก่อนเริ่มรอบใหม่"));
    if(phase==="RUN2_READY"){
      const clear=node("button","button button-outline","เริ่มรอบใหม่ · เคลียร์ข้อมูล Lab");
      clear.type="button";clear.disabled=!state.realReady||["submitting","queued","in_progress"].includes(state.resetStatus);
      clear.addEventListener("click",requestNewCycle);root.append(clear);
    }
    if(state.recentRuns.length){
      const history=node("details","notebook-history");
      history.append(node("summary","","ผล Run ที่ผ่านมา · เปิดดูหลังเคลียร์ได้"));
      const list=box("notebook-history-body");
      state.recentRuns.forEach(item=>{
        const button=node("button","button button-outline",
          (item.batch==="initial"?"Run 1":"Run 2")+" · #"+item.run_id);
        button.type="button";button.disabled=state.historyBusy;
        button.addEventListener("click",()=>showHistoryRun(item.run_id));list.append(button);
      });
      if(state.historyBusy)list.append(small("กำลังอ่านผล Run…"));
      if(state.historyRun){
        list.append(node("h3","lab-subheading","ผล Run #"+state.historyRun.runId));
        state.historyRun.result.stages.forEach(item=>{
          list.append(node("h4","",NOTEBOOK_STAGES.find(x=>x[0]===item.stage)?.[1]||item.stage),
            renderLabResult(item.evidence));
        });
      }
      history.append(list);root.append(history);
    }
    if(state.resetStatus)root.append(small("สถานะการเคลียร์ Lab: "+state.resetStatus));
    if(state.resetError)root.append(notice(state.resetError,true));
    if(state.resetUrl)root.append(link("ดู Log การเคลียร์ใน GitHub Actions",state.resetUrl));
  }

  function renderML(){
    const root=$("#app");root.replaceChildren();state.rows=[];
    const ml=state.data.ml;
    const chosen=ml.registry.selected_model;
    const score=ml.test_metrics.find(x=>x.model===chosen)||{};
    const group=state.mlGroup||"PG01";
    const features=(ml.feature_preview||[]).filter(x=>x.product_group_id===group).slice(0,5);
    const predictions=(ml.serving_predictions||[]).filter(x=>x.product_group_id===group);
    state.rows=predictions;
    $("#headerMode").textContent="ML Lab · Warehouse ประวัติจำลอง";
    $("#snapshotStamp").textContent="ML Lab · "+(state.data.generated_at_utc||"—");
    $("#footerStatus").textContent="โมเดลสาธิต · ยังไม่ผ่านเกณฑ์ WAPE";
    root.append(notice("ML Lab นี้รัน ETL จาก Source ประวัติจำลองไปยัง DuckDB Warehouse แล้วสร้าง Feature และฝึกโมเดลจาก Warehouse นั้น · แยกจาก Lab Run 1/2"));
    root.append(panel("1 · ข้อมูลจาก Warehouse ของ ML Lab",
      "ข้อมูลประวัติจำลอง "+money(ml.backtest.weeks)+" สัปดาห์ · "+money(ml.backtest.groups)+" กลุ่มสินค้า",
      contentArea(
        small("แหล่งข้อมูล: Mart_Product_Group_Daily_Performance ใน DuckDB Warehouse · สร้างจาก Source ผ่าน Database และ Data Lake"),
        small("รอบสร้างรายงาน: "+(state.data.generated_at_utc||"—")+" · ใช้ข้อมูลสังเคราะห์เพื่อการศึกษา"),
        link("ดู workflow ที่สร้าง Warehouse และรายงาน",state.data.links.ml)
      )));
    root.append(panel("2 · Feature Store",
      money(ml.feature_count)+" แถว · คีย์กลุ่มสินค้า + สัปดาห์ + วันที่อ้างอิง",
      contentArea(
        small("ตัวอย่าง Feature: ยอดขายสัปดาห์ก่อน ค่าเฉลี่ยย้อนหลัง ค่า Ads ย้อนหลัง และแผน Ads ที่บันทึกก่อนวันทำนาย"),
        dataTable([["as_of_date","ข้อมูลถึงวันที่"],["forecast_week_start","สัปดาห์ที่จะทำนาย"],
          ["product_group_id","กลุ่ม"],["revenue_last_week","ยอดขายสัปดาห์ก่อน"],
          ["planned_ads_week","แผน Ads"]],features,
          {revenue_last_week:{kind:"money"},planned_ads_week:{kind:"money"}}),
        small("ข้อมูลย้อนหลังเป็นแบบ retrospective จึงยังไม่ใช่หลักฐานพร้อมใช้จริง")
      )));
    root.append(panel("3 · ประเมินโมเดล",
      "เลือกโมเดลจากช่วง Validation แล้ววัดผลกับช่วง Test ที่แยกไว้",
      contentArea(
        add(box("metrics"),
          metric("โมเดลที่เลือก",chosen,ml.registry.model_version),
          metric("WAPE รายกลุ่ม",pct(score.group_wape_pct,2),"เกณฑ์ ≤20%"),
          metric("WAPE ทั้งร้าน",pct(score.shop_wape_pct,2),"เกณฑ์ ≤15%")),
        notice("ผลล่าสุดยังไม่ผ่านเกณฑ์ WAPE ทั้งสองข้อ · WAPE คือสัดส่วนความคลาดเคลื่อนของผลทำนาย ยิ่งต่ำยิ่งดี",true),
        dataTable([["model","โมเดล"],["group_wape_pct","WAPE รายกลุ่ม"],["shop_wape_pct","WAPE ทั้งร้าน"]],
          ml.test_metrics,{group_wape_pct:{kind:"percent",digits:2},shop_wape_pct:{kind:"percent",digits:2}})
      )));
    root.append(panel("4 · ผลทำนายจากโมเดลที่บันทึกไว้",
      "ผลจาก Warehouse ของ ML Lab · เป็นผล Replay ของสัปดาห์ทดสอบ",
      contentArea(
        chooseField("กลุ่มสินค้า",groups.map(id=>[id,title(id)]),group,v=>{state.mlGroup=v;renderML();}),
        dataTable([["forecast_week_start","สัปดาห์"],["product_group_id","กลุ่ม"],
          ["predicted_net_revenue_week","ยอดขายสุทธิคาดการณ์"]],
          predictions,{predicted_net_revenue_week:{kind:"money",digits:2}}),
        small("ผลนี้ใช้แผน Ads ที่อยู่ในชุดข้อมูลเดโม ไม่ใช่ผลของงบใหม่ที่กรอกด้านล่าง")
      )));
    const ads=labelInput("งบ Ads ที่อยากทดลอง (บาท)","number",state.mlAds||"","0","1000000");
    const discount=labelInput("ส่วนลดที่อยากทดลอง (%)","number",state.mlDiscount||"","0","100");
    ads.field.addEventListener("input",()=>{state.mlAds=ads.field.value;});
    discount.field.addEventListener("input",()=>{state.mlDiscount=discount.field.value;});
    const simulate=node("button","button button-primary","ทำนายแผนใหม่ · ยังไม่พร้อม");
    simulate.type="button";simulate.disabled=true;
    root.append(panel("5 · ลองแผน Ads และกำไร",
      "เป้าหมายคือยอดขายถึงเป้า และกำไรหลังต้นทุนไม่น้อยกว่า 10% ของ Gross Reference Sales",
      contentArea(
        box("scenario-grid",ads.label,discount.label),simulate,
        notice("โมเดลปัจจุบันทำนายจาก Warehouse ได้ แต่ WAPE ยังไม่ผ่านเกณฑ์ และยังยืนยันผลเพิ่มยอดขายจากการเปลี่ยน Ads/ส่วนลดไม่ได้ จึงยังไม่แสดงยอดขายหรือกำไรของแผนใหม่",true)
      )));
  }

  function render(){
    if(!state.data)return;
    if(state.view==="business")renderBusiness();
    if(state.view==="pipeline")renderPipeline();
    if(state.view==="ml")renderML();
    $("#exportCurrent").textContent=state.view==="business"?
      "↓ ดาวน์โหลดแถวตัวอย่างจาก Warehouse (CSV)":"↓ ดาวน์โหลดข้อมูลตัวอย่างที่แสดง (CSV)";
    $("#exportCurrent").disabled=state.view==="pipeline"||!state.rows.length;
  }
  function setView(value){
    if(!names[value])return;
    state.view=value;state.replay=false;
    if(value==="ml"&&(!state.mlGroup||!groups.includes(state.mlGroup)))state.mlGroup="PG01";
    document.querySelectorAll("[data-view]").forEach(btn=>{
      const active=btn.dataset.view===value;
      btn.classList.toggle("is-active",active);
      if(active)btn.setAttribute("aria-current","page");else btn.removeAttribute("aria-current");
    });
    $("#pageTitle").textContent=names[value][0];
    $("#pageSubtitle").textContent=names[value][1];
    $("#crumbView").textContent=names[value][2];
    $("#monthFilterWrap").classList.add("hidden");
    $("#groupFilterWrap").classList.toggle("hidden",value!=="ml");
    $("#modelFilterWrap").classList.toggle("hidden",value!=="ml");
    render();
    if(value==="business")loadWarehouseDashboard();
    if(value==="pipeline" && state.neonStatus==="not_loaded")loadNeonEvidence();
    if(value==="pipeline" && !state.realConfigChecked)loadRealCapabilities();
    if(value==="pipeline" && state.savedLabManifest===null)loadSavedLabEvidence();
  }
  function exportCsv(){
    const rows=state.rows;if(!rows.length)return;
    const columns=[...new Set(rows.flatMap(x=>Object.keys(x)))];
    const cell=x=>{
      const s=x===null||x===undefined?"":String(x);
      return /[,\"\r\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;
    };
    const csv=[columns.map(cell).join(","),...rows.map(x=>columns.map(k=>cell(x[k])).join(","))].join("\r\n");
    const blob=new Blob(["\ufeff",csv],{type:"text/csv;charset=utf-8"});
    const url=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=url;a.download=state.view==="business"?("warehouse_"+(state.warehouseSnapshot?.current_run_id||"current")+"_"+state.warehouseTable+".csv"):"tiktok_"+state.view+"_"+state.month+".csv";
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function init(){
    document.querySelectorAll("[data-view]").forEach(btn=>btn.addEventListener("click",()=>setView(btn.dataset.view)));
    $("#exportCurrent").addEventListener("click",exportCsv);
    try {
      const res=await fetch("./data/report.json",{cache:"no-cache"});
      if(!res.ok)throw Error("HTTP "+res.status);
      const d=await res.json();
      if(d.schema_version!=="decision_dashboard_v1" ||
         d.source_classification!=="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK" ||
         !Array.isArray(d.business?.months) || !Array.isArray(d.ml?.test_predictions) ||
         !Array.isArray(d.pipeline?.stages) || !d.business.months.length || !d.ml.test_predictions.length)
        throw Error("รูปแบบ Report ไม่ถูกต้องหรือไม่มีข้อมูลจริงจาก Pipeline");
      state.data=d;
      const months=d.business.months.map(x=>x.month);
      state.month=months.includes("2026-10")?"2026-10":months[months.length-1];
      $("#monthFilter").replaceChildren(...months.map(x=>{const opt=node("option","",x);opt.value=x;return opt;}));
      $("#monthFilter").value=state.month;
      $("#groupFilter").replaceChildren(...[["ALL","ทุกกลุ่มสินค้า"],...groups.map(x=>[x,title(x)])].map(x=>{
        const opt=node("option","",x[1]);opt.value=x[0];return opt;
      }));
      state.model=d.ml.registry.selected_model;
      $("#modelFilter").replaceChildren(...d.ml.test_metrics.map(x=>{
        const opt=node("option","",x.model);opt.value=x.model;return opt;
      }));
      $("#modelFilter").value=state.model;
      $("#monthFilter").addEventListener("change",e=>{state.month=e.target.value;render()});
      $("#groupFilter").addEventListener("change",e=>{state.group=e.target.value;state.sku="";render()});
      $("#modelFilter").addEventListener("change",e=>{state.model=e.target.value;state.replay=false;render()});
      $("#snapshotStamp").textContent=d.generated_at_utc?new Intl.DateTimeFormat("th-TH",{
        timeZone:"Asia/Bangkok",year:"numeric",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"
      }).format(new Date(d.generated_at_utc)):"Batch Snapshot";
      $("#headerMode").textContent="Warehouse · ตรวจสถานะสด";
      $("#footerStatus").textContent="กำลังตรวจข้อมูล Warehouse";
      $("#repoLink").href=d.links.repo;
      setView("business");
      try {
        const evidenceResponse=await fetch("./data/classroom_evidence.json",{cache:"no-cache"});
        if(evidenceResponse.ok){
          const evidence=await evidenceResponse.json();
          if(evidence.classification==="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK"
            && evidence.layers?.source && evidence.layers?.warehouse)state.evidence=evidence;
        }
      }catch(_error){
        // Explorer will clearly report that the real evidence snapshot is unavailable.
      }
      if(state.view==="pipeline")renderPipeline();
    } catch(e){
      $("#app").replaceChildren(notice("ไม่สามารถโหลด Report Snapshot: "+e.message+
        " กรุณารัน Python Exporter แล้วเปิดเว็บด้วย HTTP Server ไม่ใช่ file://",true));
      $("#headerMode").textContent="ไม่พบข้อมูลรายงาน";
      $("#exportCurrent").disabled=true;
    }
  }
  init();
})();
