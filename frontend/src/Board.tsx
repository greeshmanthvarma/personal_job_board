import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUpRight, BriefcaseBusiness, Download, RefreshCw, Search, SlidersHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { readBoard, saveTracking } from './api'
import { workspaces, visibleJobs, mergeTracking, recentPosting, type Job, type Status, type Sort } from './model'

type Draft = { status:Status; notes:string }
const date=(value:string)=>value?new Date(value).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}):'Date unavailable'
export default function Board() {
  const [jobs,setJobs]=useState<Job[]>([]), [scan,setScan]=useState<Record<string,unknown>>({})
  const [tab,setTab]=useState<Status>('new'),[query,setQuery]=useState(''),[provider,setProvider]=useState('all'),[sort,setSort]=useState<Sort>('default')
  const [closed,setClosed]=useState(false),[unverified,setUnverified]=useState(false),[limit,setLimit]=useState(40)
  const [selected,setSelected]=useState<string|null>(null),[drafts,setDrafts]=useState<Record<string,Draft>>({})
  const [loading,setLoading]=useState(false),[error,setError]=useState(''),[fetched,setFetched]=useState(''),[saving,setSaving]=useState(false)
  const [notice,setNotice]=useState<{text:string;destination:Status}|null>(null),[saveError,setSaveError]=useState('')
  const fetching=useRef(false)
  const [quickSaving,setQuickSaving]=useState<Record<string,boolean>>({}),[quickError,setQuickError]=useState('')
  const quickInFlight=useRef(new Set<string>())
  async function quickStatus(item:Job,status:Status) {
    if(status===item.status||saving||quickInFlight.current.has(item.identity))return
    if(drafts[item.identity]) {setQuickError('This job has unsaved detail edits. Save or review them in the detail view before changing its status.');return}
    quickInFlight.current.add(item.identity);setQuickSaving(prev=>({...prev,[item.identity]:true}));setQuickError('')
    try {
      const entry=await saveTracking(item.identity,status,item.notes)
      setJobs(prev=>mergeTracking(prev,item.identity,entry))
      setNotice({text:`Saved to ${workspaces.find(([s])=>s===entry.status)?.[1]}.`,destination:entry.status})
    } catch {setQuickError('Status save not confirmed. The job has not moved. Refresh to check the stored state before retrying.')}
    finally {quickInFlight.current.delete(item.identity);setQuickSaving(prev=>({...prev,[item.identity]:false}))}
  }
  const refresh=useCallback(async()=>{
    if(fetching.current)return
    fetching.current=true;setLoading(true)
    try {const data=await readBoard();setJobs(data.jobs);setScan(data.scan||{});setFetched(new Date().toLocaleTimeString());setError('')}
    catch {setError('Unable to refresh. Displaying the last loaded results, if available.')}
    finally {fetching.current=false;setLoading(false)}
  },[])
  useEffect(()=>{void refresh();const interval=setInterval(()=>{if(document.visibilityState==='visible')void refresh()},60000);return()=>clearInterval(interval)},[refresh])
  useEffect(()=>{setLimit(40)},[tab,query,provider,sort,closed,unverified])
  const rows=visibleJobs(jobs,tab,query,provider,closed,unverified,sort)
  const job=jobs.find(j=>j.identity===selected)
  const draft=selected?(drafts[selected]|| (job?{status:job.status,notes:job.notes}:undefined)):undefined
  function edit(value:Partial<Draft>) {if(selected&&draft)setDrafts(prev=>({...prev,[selected]:{...draft,...value}}))}
  async function save() {
    if(!selected||!draft||saving||quickInFlight.current.has(selected))return
    const identity=selected;setSaving(true);setSaveError('')
    try {const entry=await saveTracking(identity,draft.status,draft.notes);setJobs(prev=>mergeTracking(prev,identity,entry));setDrafts(prev=>{const next={...prev};delete next[identity];return next});setNotice({text:`Saved to ${workspaces.find(([s])=>s===entry.status)?.[1]}.`,destination:entry.status});setSelected(null)}
    catch {setSaveError('Save not confirmed. Your edits are retained. Refresh to check the stored state before retrying.')}
    finally {setSaving(false)}
  }
  const scanState=typeof scan.status==='string'?scan.status:'Not running'
  return <main className="mx-auto max-w-6xl px-5 py-9 sm:px-10 sm:py-12">
    <header className="mb-9 flex flex-wrap items-start justify-between gap-5">
      <div className="flex items-center gap-3"><BriefcaseBusiness aria-hidden="true" className="size-7" strokeWidth={1.5}/><h1 className="text-3xl font-medium tracking-tight">My Job Board</h1></div>
      <div className="flex items-center gap-2 pt-1"><Button variant="outline" size="sm" onClick={()=>void refresh()} disabled={loading}><RefreshCw className={loading?'animate-spin':''}/>Refresh</Button><Button variant="ghost" size="sm" asChild><a href="/api/export"><Download/>Export</a></Button></div>
    </header>
    <div className="mb-7 flex flex-wrap gap-x-6 gap-y-2 border-y border-border py-3 text-xs text-muted-foreground"><span>{error?'Connection unavailable':fetched?'Connected':'Connecting…'}</span><span>Last refreshed {fetched||'—'}</span><span>Scan: {scanState}</span>{typeof scan.processed_boards==='number'&&<span>{scan.processed_boards} boards checked</span>}{!!scan.scheduler&&typeof scan.scheduler==='object'&&'heartbeat_at' in scan.scheduler&&<span>Scheduler: {Date.now()-new Date(String(scan.scheduler.heartbeat_at)).getTime()>600000?'stale':'active'}</span>}</div>
    {error&&<p role="alert" className="mb-4 rounded-md border p-3 text-sm">{error}</p>}
    {quickError&&<p role="alert" className="mb-4 rounded-md border p-3 text-sm">{quickError}</p>}
    {notice&&<div role="status" className="mb-4 flex items-center gap-3 text-sm">{notice.text}<Button size="sm" variant="link" onClick={()=>{setTab(notice.destination);setNotice(null)}}>View tab</Button><Button size="sm" variant="ghost" onClick={()=>setNotice(null)}>Dismiss</Button></div>}
    <Tabs value={tab} onValueChange={value=>setTab(value as Status)}>
      <div className="overflow-x-auto pb-2"><TabsList variant="line" className="h-11 min-w-max gap-4">{workspaces.map(([status,label])=><TabsTrigger key={status} value={status} className="gap-2 px-1 text-sm">{label}<span className="text-[11px] tabular-nums text-muted-foreground">{jobs.filter(j=>j.status===status&&(status!=='new'||recentPosting(j))).length}</span></TabsTrigger>)}</TabsList></div>
      <section aria-label="Filter jobs" className="my-5 flex flex-wrap items-center gap-3"><div className="relative min-w-52 flex-1"><Search className="absolute left-3 top-2.5 size-4 text-muted-foreground"/><Input aria-label="Search jobs" placeholder="Search company, role, or notes…" value={query} onChange={e=>setQuery(e.target.value)} className="pl-9"/></div>
        <Select value={provider} onValueChange={setProvider}><SelectTrigger aria-label="Job source" className="w-36"><SelectValue/></SelectTrigger><SelectContent>{['all','ashby','greenhouse','lever'].map(p=><SelectItem key={p} value={p}>{p==='all'?'All sources':p[0].toUpperCase()+p.slice(1)}</SelectItem>)}</SelectContent></Select>
        <Select value={sort} onValueChange={v=>setSort(v as Sort)}><SelectTrigger aria-label="Sort jobs" className="w-44"><SlidersHorizontal className="size-3"/><SelectValue/></SelectTrigger><SelectContent><SelectItem value="default">{tab==='new'||tab==='saved'?'Recommended':'Recently updated'}</SelectItem><SelectItem value="newest">Newest posted</SelectItem><SelectItem value="fit">Best fit</SelectItem></SelectContent></Select>
      </section>
      {tab==='new'&&<div className="mb-5 flex gap-5 text-xs text-muted-foreground"><label className="flex items-center gap-2"><Checkbox checked={closed} onCheckedChange={v=>setClosed(v===true)}/>Include closed</label><label className="flex items-center gap-2"><Checkbox checked={unverified} onCheckedChange={v=>setUnverified(v===true)}/>Include unverified</label></div>}
      {workspaces.map(([status,label])=><TabsContent key={status} value={status}>
        <div className="mb-2 flex justify-between text-xs text-muted-foreground"><span>{rows.length} {rows.length===1?'opportunity':'opportunities'}</span><span>{tab==='new'?'Relevance + recency':'Your application workspace'}</span></div>
        {rows.slice(0,limit).map(j=><article key={j.identity} className="group flex flex-wrap items-center gap-4 border-b border-border py-5"><div className="flex size-10 shrink-0 items-center justify-center rounded-md border bg-secondary/30 text-sm font-medium" aria-hidden="true">{j.company.slice(0,2).toUpperCase()}</div><div className="min-w-0 flex-1"><p className="mb-1 text-xs text-muted-foreground">{j.company}</p><button className="text-left text-[15px] font-medium leading-snug hover:underline focus-visible:outline-2 focus-visible:outline-ring" onClick={()=>{setSelected(j.identity);setSaveError('')}}>{j.title}</button><div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground"><span>{j.location||'Location unspecified'}</span><span className="capitalize">{j.portal}</span><span>{date(j.posted_at)}</span>{j.is_listed!==true&&<span>{j.is_listed===false?'Closed':'Unverified'}</span>}</div></div><div className="hidden text-right sm:block"><Badge variant="outline" className="font-normal">{j.fit===null?'Not assessed':`${Math.round(j.fit*100)}% fit`}</Badge><p className="mt-2 text-[10px] text-muted-foreground">{j.fit===null?'Awaiting assessment':'Jev assessment'}</p></div><div className="flex w-full items-center justify-end gap-2 sm:w-auto">{/^https:\/\//i.test(j.link)&&<Button asChild variant="outline" size="sm"><a href={j.link} target="_blank" rel="noopener noreferrer" aria-label={`Apply to ${j.title} at ${j.company}`}>Apply<ArrowUpRight/></a></Button>}<Select value={j.status} onValueChange={value=>void quickStatus(j,value as Status)} disabled={saving||!!quickSaving[j.identity]}><SelectTrigger aria-label={`Status for ${j.title} at ${j.company}`} className="w-40"><SelectValue/></SelectTrigger><SelectContent>{workspaces.map(([s,l])=><SelectItem key={s} value={s}>{s==='new'?'New':l}</SelectItem>)}</SelectContent></Select></div></article>)}
        {!rows.length&&<div className="py-20 text-center"><h2 className="text-lg">{loading?'Loading opportunities…':error&&!fetched?'Results unavailable':`Nothing in ${label.toLowerCase()} yet.`}</h2><p className="mt-2 text-sm text-muted-foreground">{query?'Try a different search or filter.':tab==='new'?'Refresh after the next scan.':'Jobs appear here when you save their status.'}</p></div>}
        {rows.length>limit&&<Button variant="outline" className="mt-6" onClick={()=>setLimit(n=>n+40)}>Show more</Button>}
      </TabsContent>)}
    </Tabs>
    <Sheet open={!!selected} onOpenChange={open=>{if(!open&&!saving)setSelected(null)}}><SheetContent className="w-full overflow-y-auto sm:max-w-xl"><SheetHeader><SheetTitle>{job?.title||'Unsaved job edits'}</SheetTitle><SheetDescription>{job?.company} · {job?.location}</SheetDescription></SheetHeader><div className="space-y-6 px-6 pb-8">
      {job&&<><div className="flex flex-wrap gap-2"><Badge variant="outline">{job.fit===null?'Not assessed':`${Math.round(job.fit*100)}% fit`}</Badge><Badge variant="secondary">{job.is_listed===true?'Open':job.is_listed===false?'Closed':'Unverified'}</Badge></div>{/^https:\/\//i.test(job.link)&&<Button asChild variant="outline"><a href={job.link} target="_blank" rel="noopener noreferrer">Open application<ArrowUpRight/></a></Button>}<div><h3 className="mb-2 text-sm font-medium">Why this role</h3><p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{job.assessment||'No assessment available.'}</p></div><details><summary className="cursor-pointer text-sm font-medium">Job description</summary><p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{job.description||'Description unavailable.'}</p></details></>}
      {draft&&<div className="space-y-4 border-t pt-5"><div className="space-y-2"><label className="text-sm" id="status-label">Application status</label><Select value={draft.status} onValueChange={v=>edit({status:v as Status})} disabled={saving}><SelectTrigger aria-labelledby="status-label" className="w-full"><SelectValue/></SelectTrigger><SelectContent>{workspaces.map(([s,l])=><SelectItem key={s} value={s}>{s==='new'?'New':l}</SelectItem>)}</SelectContent></Select></div><div className="space-y-2"><label htmlFor="notes" className="text-sm">Notes</label><Textarea id="notes" placeholder="Keep the useful details here." value={draft.notes} maxLength={10000} onChange={e=>edit({notes:e.target.value})} disabled={saving} className="min-h-28"/></div>{saveError&&<p role="alert" className="text-sm">{saveError}</p>}<Button onClick={()=>void save()} disabled={saving||!job}>{saving?'Saving…':'Save tracking'}</Button>{job?.applied_at&&<p className="text-xs text-muted-foreground">Applied {date(job.applied_at)}</p>}<p className="text-xs text-muted-foreground">Status moves only after a confirmed save. Applying happens on the employer’s site.</p></div>}
    </div></SheetContent></Sheet>
    <footer className="mt-12 text-xs text-muted-foreground">Private by design. Apply deliberately.</footer>
  </main>
}
