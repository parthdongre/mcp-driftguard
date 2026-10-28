"""End-to-end local STDIO fixture costs, serialization, crash and lifecycle checks."""
import concurrent.futures,json,sys,tempfile,threading,time
from pathlib import Path
from experiments.validate_submission_systems import metrics
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tests'))
from test_gateway_transport import FIXTURE,tool
from driftguard.gateway import GuardStore,GateError
from driftguard.gateway_transport import ProtectedGateway,StdioConfig,TransportError

def main():
 out=ROOT/'artifacts/submission-systems';out.mkdir(parents=True,exist_ok=True)
 report={'scope':'Actual local authored STDIO subprocess, not a public MCP server. Includes catalog refresh and invocation round trip.','targets':{'sequential_p95_ms_max':100,'concurrent_errors_max':0,'executions_after_revoke_max':0,'cycles_without_child_leaks':10}}
 with tempfile.TemporaryDirectory(prefix='driftguard-gateway-cost-') as name:
  folder=Path(name);(folder/'server.py').write_text(FIXTURE);(folder/'control.json').write_text(json.dumps({'tools':[tool()]}))
  config=StdioConfig('fixture',(sys.executable,str(folder/'server.py'),str(folder)),cwd=str(folder))
  with GuardStore(folder/'state.sqlite3') as store:
   gateway=ProtectedGateway(config,store)
   def approve():
    r=store.get_tool('fixture','weather');store.approve('fixture','weather',expected_hash=r['sha256'],expected_revision=r['revision'])
   def invoke(_=0):
    start=time.perf_counter();result=gateway.call('weather',{});assert result['content'][0]['text']=='Sunny';return 1000*(time.perf_counter()-start)
   try:
    approve();[invoke() for _ in range(10)];report['sequential']=metrics([invoke() for _ in range(200)])
    start=time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool: samples=list(pool.map(invoke,range(400)))
    report['concurrent']={**metrics(samples),'workers':8,'calls_s':400/(time.perf_counter()-start),'errors':0}
    r=store.get_tool('fixture','weather');store.revoke('fixture','weather',expected_hash=r['sha256'],expected_revision=r['revision'])
    for _ in range(20):
     try:gateway.call('weather',{})
     except GateError:pass
     else:raise AssertionError('Call executed after revoke')
    report['revoked_calls_blocked']=20
    gateway.peer.process.kill();gateway.peer.process.wait(timeout=5)
    try:gateway.call('weather',{})
    except (TransportError,GateError):pass
    else:raise AssertionError('Dead upstream accepted a call')
    report['dead_upstream_call_blocked']=True
   finally:gateway.close()
   children=[]
   for _ in range(10):
    g=ProtectedGateway(config,store);children.append(g.peer.process)
    try:
     assert g.list_approved()==[]
     approve();assert g.call('weather',{})['content'][0]['text']=='Sunny'
    finally:g.close()
   report['reconnect_cycles']=10;report['all_owned_children_reaped']=all(p.poll() is not None for p in children)
 report['checks']={'sequential_p95':report['sequential']['p95_ms']<=100,'lifecycle':report['all_owned_children_reaped'],'revocation':report['revoked_calls_blocked']==20,'concurrency':report['concurrent']['n']==400}
 report['status']='passed' if all(report['checks'].values()) else 'failed'
 (out/'gateway-profile.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
