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

export type FitVerdict = 'yes' | 'no' | 'uncertain'
export type FitCheck = { key: string; label: string; detail: string; verdict: FitVerdict; score: number }
export type FitExplanation = { verdict: FitVerdict; summary: string; checks: FitCheck[] }

const FIT_CHECKS = [
  { key: 'role_family', label: 'Role type', detail: 'Software, AI, full-stack, backend, or agent and retrieval work.' },
  { key: 'level', label: 'Experience level', detail: 'Accepts new-graduate or entry-level experience, including stated substitutions.' },
  { key: 'responsibilities', label: 'Day-to-day work', detail: 'Core responsibilities match full-stack, backend, agent, retrieval, or infrastructure work.' },
  { key: 'qualifications', label: 'Required qualifications', detail: 'Stated requirements are supported by your profile, or the posting treats them as flexible.' },
] as const

function joinLabels(labels: string[]) {
  if (labels.length <= 1) return labels[0] ?? ''
  if (labels.length === 2) return `${labels[0]} and ${labels[1]}`
  return `${labels.slice(0, -1).join(', ')}, and ${labels[labels.length - 1]}`
}

function clause(labels: string[], ending: string) {
  const phrase = `${joinLabels(labels)} ${labels.length === 1 ? 'is' : 'are'} ${ending}`
  return phrase.charAt(0).toUpperCase() + phrase.slice(1)
}

function summary(verdict: FitVerdict, checks: FitCheck[]) {
  const named = (value: FitVerdict) => checks.filter(check => check.verdict === value).map(check => check.label.toLowerCase())
  if (verdict === 'yes' && checks.every(check => check.verdict === 'yes')) {
    return 'Clear match. Role type, experience level, day-to-day work, and required qualifications are all a yes.'
  }
  if (verdict === 'no') {
    const lead = `Not a match. ${clause(named('no'), 'a no')}.`
    const unclear = named('uncertain')
    return unclear.length ? `${lead} ${clause(unclear, 'still unclear')}.` : lead
  }
  const yeses = named('yes')
  const lead = `Possible match. ${clause(named('uncertain'), 'still unclear')}.`
  return yeses.length ? `${lead} ${clause(yeses, 'a yes')}.` : lead
}

export function explainAssessment(assessment: string): FitExplanation | null {
  const match = /^(yes|no|uncertain):\s*(.+)$/s.exec(assessment.trim())
  if (!match) return null
  const verdict = match[1] as FitVerdict
  const found = new Map<string, { verdict: FitVerdict; score: number }>()
  for (const part of match[2].matchAll(/(role_family|level|responsibilities|qualifications)\s+(yes|no|uncertain)\s+\((\d+(?:\.\d+)?)\)/g)) {
    const score = Number(part[3])
    if (!Number.isFinite(score)) return null
    found.set(part[1], { verdict: part[2] as FitVerdict, score })
  }
  if (found.size !== FIT_CHECKS.length) return null
  const checks = FIT_CHECKS.map(check => {
    const parsed = found.get(check.key)
    if (!parsed) return null
    return { ...check, verdict: parsed.verdict, score: parsed.score }
  })
  if (checks.some(check => check === null)) return null
  return { verdict, summary: summary(verdict, checks as FitCheck[]), checks: checks as FitCheck[] }
}
