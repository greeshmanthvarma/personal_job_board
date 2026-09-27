export const workspaces = [ ['new','Results'],['saved','Saved'],['applied','Applied'],['interviewing','Interviewing'],['offer','Offers'],['rejected','Rejected'],['skipped','Skipped'],['needs_verification','Needs verification'] ] as const
export type Status = typeof workspaces[number][0]
export type Tracking = {status:Status;notes:string;applied_at:string;updated_at:string}
export type Job = Tracking & {identity:string; company:string;title:string;location:string;portal:string;link:string;description?:string;assessment?:string;fit:number|null;priority:number;posted_at:string;checked_at:string;is_listed:boolean|null}
export type Sort = 'default'|'newest'|'fit'
export function recentPosting(job:Job,now=Date.now()) {
  const posted=Date.parse(job.posted_at)
  return Number.isFinite(posted)&&posted<=now&&now-posted<=7*24*60*60*1000
}
export function visibleJobs(jobs:Job[],status:Status,query:string,provider:string,closed:boolean,unverified:boolean,sort:Sort) {
  const term=query.trim().toLowerCase()
  const now=Date.now()
  return jobs.filter(j=>j.status===status && (provider==='all'||j.portal===provider) && (!term||[j.title,j.company,j.location,j.notes].join(' ').toLowerCase().includes(term)) && (status!=='new'||(recentPosting(j,now)&&(j.is_listed!==false||closed)&&(j.is_listed!==null||unverified)))).sort((a,b)=>sort==='fit'?(b.fit??-1)-(a.fit??-1):sort==='newest'?b.posted_at.localeCompare(a.posted_at):status==='new'||status==='saved'?b.priority-a.priority:b.updated_at.localeCompare(a.updated_at))
}
export function mergeTracking(jobs:Job[],identity:string,entry:Tracking) {return jobs.map(j=>j.identity===identity?{...j,...entry}:j)}
