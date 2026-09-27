import { describe, it, expect } from 'vitest'
import { visibleJobs, mergeTracking, type Job } from './model'
const base: Job = {identity:'ashby\t1',company:'Example',title:'Engineer',location:'US',portal:'ashby',link:'https://example.com',description:'',assessment:'',fit:null,priority:0,status:'new',notes:'',posted_at:'',checked_at:'',is_listed:true,applied_at:'',updated_at:''}
describe('status workspaces', () => {
  it('partitions Results from Applied', () => {
    const applied={...base,identity:'ashby\t2',status:'applied' as const}
    expect(visibleJobs([base,applied],'new','', 'all',false,false,'default')).toEqual([base])
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
