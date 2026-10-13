const fs=require('fs'),path=require('path'),vm=require('vm');
const auditRoot=process.env.V126_REVIEW_ROOT||__dirname;
const nodes={classesFeed:{innerHTML:''},studentAccountsList:{innerHTML:''}};
let pending=[],requests=[];
const ctx={document:{addEventListener(){},getElementById(id){return nodes[id]||null},querySelectorAll(){return[]}},window:{addEventListener(){}},console:{log(){},warn(){},error(){}},setInterval(){return 1},clearInterval(){},setTimeout(){return 1},fetch(url,opt){requests.push({url,body:opt?.body});return new Promise(resolve=>pending.push(resolve));}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(auditRoot,'source/server/static/js/app.js'),'utf8')+'\nglobalThis.auditState=appState;globalThis.originalRender=renderClassesList;renderClassesList=()=>{};updateUIElements=()=>{};showToast=()=>{};',ctx);
const result=[];
function record(id,observed,expected){result.push({id,observed,issue_observation:expected,confirmed:JSON.stringify(observed)===JSON.stringify(expected)});}
(async()=>{
 ctx.auditState.activeUsername='fixture-A';const a=ctx.fetchClasses();ctx.auditState.activeUsername='fixture-B';const b=ctx.fetchClasses();
 pending[1]({json:async()=>({classes:[{courseName:'B'}],username:'fixture-B'})});await b;pending[0]({json:async()=>({classes:[{courseName:'A'}],username:'fixture-A'})});await a;
 record('F01',{active:ctx.auditState.activeUsername,course:ctx.auditState.classes[0].courseName},{active:'fixture-B',course:'A'});
 pending=[];requests=[];const click=ctx.manualSignIn('fixture-A-schedule');pending[0]({json:async()=>({success:false,message:'synthetic response'})});await click;
 record('F02',{body:JSON.parse(requests[0].body),usernameField:'username' in JSON.parse(requests[0].body)},{body:{course_id:'fixture-A-schedule'},usernameField:false});
 ctx.originalRender([{courseSchedId:"fixture');globalThis.auditInjected=true;//",courseName:'Synthetic',signStatus:0}]);
 const handler=nodes.classesFeed.innerHTML.match(/onclick="([^"]+)"/)[1];ctx.manualSignIn=()=>{};vm.runInContext(handler,ctx);
 record('F03',ctx.auditInjected===true,true);
 ctx.originalRender([{courseSchedId:'fixture',courseName:'<img src=x onerror=alert(1)>',signStatus:0}]);
 record('F04',nodes.classesFeed.innerHTML.includes('<img src=x'),false);
 fs.writeFileSync(path.join(auditRoot,'frontend-review.json'),JSON.stringify({scenarios:result,confirmed:result.filter(x=>x.confirmed).length,scope:'Actual app.js in Node VM; F03 evaluates generated click handler with synthetic ID. No real browser exploitation claimed.'},null,2));
 console.log(JSON.stringify({count:result.length,confirmed:result.filter(x=>x.confirmed).length,results:result}));
 if(result.some(x=>!x.confirmed))process.exitCode=1;
})().catch(e=>{console.error(e.stack);process.exitCode=1});
