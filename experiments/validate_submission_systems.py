"""Offline systems validation. Authored subprocess fixture; no external MCP claims."""
from __future__ import annotations
import argparse,concurrent.futures,hashlib,json,math,os,platform,sqlite3,subprocess,sys,tempfile,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
from driftguard.gateway import GuardStore,ServerIdentity,GateError
from driftguard.gateway_transport import ProtectedGateway,StdioConfig,MODERN
from test_gateway_transport import FIXTURE,tool

DEFINITION={'name':'search','inputSchema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query'],'additionalProperties':False}}

def setup(path):
    s=GuardStore(path);s.register_server(ServerIdentity('local','fixed-config','fixed-local-user'))
    r=s.ingest_catalog('local',[DEFINITION])[0]
    r=s.approve('local','search',expected_hash=r['sha256'],expected_revision=r['revision'])
    return s,r

def dispatch(s,r,callback=lambda n,a:a):
    return s.dispatch('local','search',{'query':'public test'},callback,expected_hash=r['sha256'],expected_revision=r['revision'])

def metrics(samples):
    samples=sorted(samples)
    return {'n':len(samples),'p50_ms':samples[math.ceil(.5*len(samples))-1],'p95_ms':samples[math.ceil(.95*len(samples))-1],'p99_ms':samples[math.ceil(.99*len(samples))-1],'max_ms':max(samples)}

def rss():
    try:return int(Path('/proc/self/status').read_text().split('VmRSS:')[1].split()[0])*1024
    except (OSError,IndexError):return None

def worker(folder,mode):
    folder=Path(folder)
    if mode=='transaction':
        with GuardStore(folder/'crash.sqlite3') as s:
            with s._transaction():
                s._event('uncommitted_crash_probe')
                (folder/'ready').write_text('ready')
                time.sleep(60)
    else:
        s=GuardStore(folder/'gateway.sqlite3')
        gateway=ProtectedGateway(StdioConfig('fixture',(sys.executable,str(folder/'server.py'),str(folder)),cwd=str(folder)),s)
        r=s.get_tool('fixture','weather');s.approve('fixture','weather',expected_hash=r['sha256'],expected_revision=r['revision'])
        (folder/'ready').write_text(json.dumps({'upstream_pid':gateway.peer.process.pid}))
        time.sleep(60)

def await_ready(p,marker):
    end=time.monotonic()+15
    while time.monotonic()<end:
        if marker.exists():return
        if p.poll() is not None:raise RuntimeError('Crash worker exited before ready')
        time.sleep(.01)
    raise TimeoutError('Crash worker did not become ready')

def crash_checks(folder):
    folder.mkdir(); result={}
    with GuardStore(folder/'crash.sqlite3') as s:s.record_event('committed_probe')
    p=subprocess.Popen([sys.executable,__file__,'--worker',str(folder),'transaction'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        await_ready(p,folder/'ready');p.kill();p.wait(timeout=5)
        with GuardStore(folder/'crash.sqlite3') as s:
            events={e['event_type'] for e in s.events()}
            assert 'committed_probe' in events and 'uncommitted_crash_probe' not in events
        with sqlite3.connect(folder/'crash.sqlite3') as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        result['killed_transaction_rolls_back_without_losing_committed_event']=True
    finally:
        if p.poll() is None:p.kill();p.wait()
    (folder/'ready').unlink();(folder/'server.py').write_text(FIXTURE);(folder/'control.json').write_text(json.dumps({'tools':[tool()]}))
    p=subprocess.Popen([sys.executable,__file__,'--worker',str(folder),'gateway'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    child=None
    try:
        await_ready(p,folder/'ready');child=json.loads((folder/'ready').read_text())['upstream_pid'];p.kill();p.wait(timeout=5)
        with GuardStore(folder/'gateway.sqlite3') as s:
            gateway=ProtectedGateway(StdioConfig('fixture',(sys.executable,str(folder/'server.py'),str(folder)),cwd=str(folder)),s)
            try:
                assert gateway.list_approved()==[]
                try:gateway.call('weather',{})
                except GateError:pass
                else:raise AssertionError('Crash recovery reused approval')
                assert not (folder/'calls.jsonl').exists()
                result['killed_gateway_fresh_session_requires_review']=True
            finally:gateway.close()
    finally:
        if p.poll() is None:p.kill();p.wait()
        if child:
            try:os.killpg(child,9)
            except ProcessLookupError:pass
    return result

def concurrency(folder):
    path=folder/'concurrent.sqlite3';store,row=setup(path);store.close()
    def task(_):
        with GuardStore(path) as s:
            samples=[]
            for i in range(50):
                start=time.perf_counter();assert dispatch(s,row)=={'query':'public test'};samples.append(1000*(time.perf_counter()-start))
            return samples
    start=time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        samples=sum([f.result(timeout=60) for f in [pool.submit(task,i) for i in range(8)]],[])
    duration=time.perf_counter()-start
    with GuardStore(path) as s:
        assert sum(e['event_type']=='call_completed' for e in s.events(10000))==400
    # A revocation on a separate connection must serialize behind an in-flight call.
    entered=threading.Event();release=threading.Event();revoked=threading.Event()
    with GuardStore(path) as a,GuardStore(path) as b:
        def held(n,args):entered.set();assert release.wait(5);return 'done'
        def revoker():
            assert entered.wait(5)
            b.revoke('local','search',expected_hash=row['sha256'],expected_revision=row['revision']);revoked.set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            running=pool.submit(dispatch,a,row,held); assert entered.wait(5)
            rev=pool.submit(revoker);release.set();assert running.result(timeout=10)=='done';rev.result(timeout=10);assert revoked.is_set()
        for _ in range(100):
            try:dispatch(a,row,lambda *a:(_ for _ in ()).throw(AssertionError('Executed after revoke')))
            except GateError:pass
            else:raise AssertionError('Post-revocation execution accepted')
    return {'workers':8,'independent_sqlite_connections':True,'successful_calls':400,'seconds':duration,'throughput_calls_s':400/duration,'latency':metrics(samples),'post_revocation_blocks':100}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=300);parser.add_argument('--worker',nargs=2);args=parser.parse_args()
    if args.worker:return worker(*args.worker)
    if not 1 <= args.seconds <= 86400: parser.error('--seconds must be between 1 and 86400')
    out=ROOT/'artifacts/submission-systems';out.mkdir(parents=True,exist_ok=True)
    report={'source_sha256':hashlib.sha256(b''.join(p.relative_to(ROOT).as_posix().encode()+p.read_bytes() for p in sorted((ROOT/'src/driftguard').glob('*.py')))).hexdigest(),'scope':'Linux local store + authored STDIO fixture. No real remote MCP, browser, native installer, embedding/model or independent detection evaluation.','python':sys.version,'platform':platform.platform(),'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'started_at':time.time(),'targets':{'single_store_dispatch_p95_ms_max':50,'concurrent_errors_max':0,'post_revoke_executions_max':0,'crash_checks_all_pass':True,'soak_seconds_min':args.seconds,'soak_errors_max':0,'rss_growth_mib_max':64},'results':{},'status':'running'}
    def save():
        temp=out/'results.tmp';temp.write_text(json.dumps(report,indent=2));temp.replace(out/'results.json')
    save()
    try:
        with tempfile.TemporaryDirectory(prefix='driftguard-systems-') as temp:
            folder=Path(temp);s,row=setup(folder/'latency.sqlite3')
            samples=[]
            for _ in range(20):dispatch(s,row)
            for _ in range(1000):
                start=time.perf_counter();dispatch(s,row);samples.append(1000*(time.perf_counter()-start))
            s.close();report['results']['performance']=metrics(samples);save();print('Performance measured',flush=True)
            report['results']['concurrency']=concurrency(folder);save();print('Concurrency and revocation checks passed',flush=True)
            report['results']['crash_recovery']=crash_checks(folder/'crashes');save();print('Forced crash recovery checks passed',flush=True)
            store,row=setup(folder/'soak.sqlite3');before=rss();counts={'calls':0,'invalid_blocks':0,'cycles':0};start=time.monotonic();deadline=start+args.seconds
            while time.monotonic()<deadline:
                for _ in range(10):dispatch(store,row);counts['calls']+=1
                try:store.dispatch('local','search',{'query':42},lambda *a:(_ for _ in ()).throw(AssertionError('Invalid invocation executed')),expected_hash=row['sha256'],expected_revision=row['revision'])
                except GateError:counts['invalid_blocks']+=1
                else:raise AssertionError('Invalid invocation accepted')
                # Bounded disk reads exercise persisted review state throughout the run.
                assert store.get_tool('local','search')['status']=='approved';counts['cycles']+=1
                if counts['cycles']%25==0:
                    report['results']['soak_progress']={'elapsed_s':time.monotonic()-start,**counts};save()
                time.sleep(.2)
            after=rss();store.close()
            report['results']['sustained_operation']={'seconds':time.monotonic()-start,**counts,'rss_before_bytes':before,'rss_after_bytes':after,'rss_growth_mib':(after-before)/1048576 if before and after else None,'database_bytes':(folder/'soak.sqlite3').stat().st_size,'errors':0}
            checks={'latency':report['results']['performance']['p95_ms']<=50,'concurrency':True,'crashes':all(report['results']['crash_recovery'].values()),'soak_duration':report['results']['sustained_operation']['seconds']>=args.seconds,'rss':before is not None and after is not None and after-before<=64*1048576}
            report['checks']=checks;report['status']='passed' if all(checks.values()) else 'failed';save()
    except Exception as error:
        report.update(status='failed',error=f'{type(error).__name__}: {error}');save();raise
    report['finished_at']=time.time();save();print(json.dumps(report,indent=2));return 0 if report['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
