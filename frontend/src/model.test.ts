import { describe, it, expect } from 'vitest'
import { explainAssessment, visibleJobs, mergeTracking, recentPosting, type Job } from './model'
const base: Job = {identity:'ashby\t1',company:'Example',title:'Engineer',location:'US',portal:'ashby',link:'https://example.com',description:'',assessment:'',fit:null,priority:0,status:'new',notes:'',posted_at:'',checked_at:'',is_listed:true,applied_at:'',updated_at:''}
describe('status workspaces', () => {
  it('partitions Results from Applied', () => {
    const applied={...base,identity:'ashby\t2',status:'applied' as const}
    const fresh={...base,posted_at:new Date().toISOString()}
    expect(visibleJobs([fresh,applied],'new','', 'all',false,false,'default')).toEqual([fresh])
  })
  it('keeps expired tracked jobs', () => {
    const applied={...base,status:'applied' as const,is_listed:false}
    expect(visibleJobs([applied],'applied','', 'all',false,false,'default')).toEqual([applied])
  })
  it('moves only immutable confirmed updates', () => {
    const updated=mergeTracking([base],base.identity,{status:'applied',notes:'hello',updated_at:'2026-09-26T12:00:00Z',applied_at:'2026-09-26T12:00:00Z'})
    expect(base.status).toBe('new')
    expect(visibleJobs(updated,'new','', 'all',false,false,'default')).toHaveLength(0)
    expect(visibleJobs(updated,'applied','', 'all',false,false,'default')).toHaveLength(1)
  })
})
it('explains a mixed assessment in plain language', () => {
  const explained = explainAssessment('no: role_family uncertain (0.56); level no (0.15); responsibilities uncertain (0.28); qualifications no (0.17)')
  expect(explained?.summary).toBe('Not a match. Experience level and required qualifications are a no. Role type and day-to-day work are still unclear.')
  expect(explained?.checks.map(check => [check.label, check.verdict, check.score])).toEqual([
    ['Role type', 'uncertain', 0.56],
    ['Experience level', 'no', 0.15],
    ['Day-to-day work', 'uncertain', 0.28],
    ['Required qualifications', 'no', 0.17],
  ])
})
it('explains a clear match and leaves other text unchanged', () => {
  expect(explainAssessment('yes: role_family yes (0.91); level yes (0.88); responsibilities yes (0.90); qualifications yes (0.86)')?.verdict).toBe('yes')
  expect(explainAssessment('uncertain: role_family yes (0.92); level uncertain (0.68); responsibilities yes (0.86); qualifications uncertain (0.75)')?.summary).toBe('Possible match. Experience level and required qualifications are still unclear. Role type and day-to-day work are a yes.')
  expect(explainAssessment('')).toBeNull()
  expect(explainAssessment('posted more than 24 hours ago')).toBeNull()
  expect(explainAssessment('yes: role_family yes (0.90)')).toBeNull()
})
it('excludes old, missing, invalid and future dates from Results',()=>{
  const now=Date.now()
  for(const posted_at of ['', 'invalid',new Date(now-8*86400000).toISOString(),new Date(now+86400000).toISOString()]) {
    expect(visibleJobs([{...base,posted_at}],'new','','all',true,true,'default')).toHaveLength(0)
  }
  expect(recentPosting({...base,posted_at:new Date(now-7*86400000).toISOString()},now)).toBe(true)
  expect(recentPosting({...base,posted_at:new Date(now-7*86400000-1).toISOString()},now)).toBe(false)
})
