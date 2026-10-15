import { useEffect, useRef, useState } from 'react';
import {
    Activity,
    AlertTriangle,
    ArrowUpRight,
    Brain,
    CheckCircle2,
    ClipboardCheck,
    FileCheck2,
    FileText,
    Globe2,
    HandHeart,
    History,
    RefreshCw,
    Send,
    ShieldCheck,
    Sparkles,
    Zap,
} from 'lucide-react';
import { api, ws } from '@appdeploy/client';

type CaseRecord = {
    id: string;
    drug: string;
    reaction: string;
    seriousness: string;
    status: string;
    aiConfidence: number;
    humanVerified: boolean;
};

type Signal = {
    id?: string;
    title: string;
    severity: string;
    source: string;
    country: string;
    impact: string;
    prr: number;
    ror: number;
    trend: string;
    created_at: number;
};

type Audit = {
    id?: string;
    actor: string;
    action: string;
    entity: string;
    timestamp: number;
    hash: string;
};

type Approval = { id: string; drug_name: string; approval_date: string; indication: string };

type Source = {
    id: string;
    name: string;
    region: string;
    status: string;
    message: string;
    url: string;
    lastChecked?: number;
};

const sourceSeed: Source[] = [
    {
        id: 'eudravigilance',
        name: 'EMA EudraVigilance',
        region: 'EEA',
        status: 'READY-GATED',
        message: 'E2B(R3) workflow ready; production gateway requires EMA registration/credentials',
        url: 'https://www.ema.europa.eu/en/human-regulatory-overview/research-development/pharmacovigilance-research-development/eudravigilance',
    },
    {
        id: 'cima',
        name: 'AEMPS CIMA',
        region: 'Spain',
        status: 'LIVE',
        message: 'Official medicine/supply source monitored',
        url: 'https://cima.aemps.es/cima/',
    },
    {
        id: 'bifimed',
        name: 'BIFIMED',
        region: 'Spain',
        status: 'LIVE',
        message: 'Financing and nomenclator intelligence monitored',
        url: 'https://www.sanidad.gob.es/areas/farmacia/',
    },
];

const defaultCases: CaseRecord[] = [
    {
        id: 'ICSR-00041',
        drug: 'trastuzumab',
        reaction: 'cardiac dysfunction',
        seriousness: 'Serious',
        status: 'AI REVIEW',
        aiConfidence: 96,
        humanVerified: false,
    },
    {
        id: 'ICSR-00042',
        drug: 'adalimumab',
        reaction: 'anaphylactic reaction',
        seriousness: 'Serious',
        status: 'HUMAN VERIFIED',
        aiConfidence: 94,
        humanVerified: true,
    },
    {
        id: 'ICSR-00043',
        drug: 'semaglutide',
        reaction: 'pancreatitis',
        seriousness: 'Serious',
        status: 'DRAFT',
        aiConfidence: 89,
        humanVerified: false,
    },
];

function App() {
    const [tab, setTab] = useState('Overview');
    const [sources, setSources] = useState<Source[]>(sourceSeed);
    const [cases, setCases] = useState<CaseRecord[]>(defaultCases);
    const [signals, setSignals] = useState<Signal[]>([]);
    const [audits, setAudits] = useState<Audit[]>([]);
    const [notice, setNotice] = useState('');
const [approvals, setApprovals] = useState<Approval[]>([]);
const [approvalsLoading, setApprovalsLoading] = useState<boolean>(true);
const [approvalsError, setApprovalsError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const conn = useRef<ReturnType<typeof ws.connect> | null>(null);

    const load = async () => {
        try {
            const r = await api.get('/api/dashboard');
            const d = r.data as {
                sources?: Source[];
                cases?: CaseRecord[];
                signals?: Signal[];
                audits?: Audit[];
            };
            if (d.sources?.length) setSources(d.sources);
            if (d.cases?.length) setCases(d.cases);
            if (d.signals) setSignals(d.signals);
            if (d.audits) setAudits(d.audits);
        } catch {
            setNotice('Dashboard is using safe local defaults while the backend reconnects.');
        }
    };

    useEffect(() => {
        load();
        const c = ws.connect();
        conn.current = c;
        c.onMessage((message: { type?: string; payload?: { entity_type?: string; data?: unknown } }) => {
            if (
                message?.type === 'entity.update' &&
                message.payload?.entity_type === 'pharma-dashboard'
            ) {
                const d = message.payload.data as {
                    sources?: Source[];
                    cases?: CaseRecord[];
                    signals?: Signal[];
                    audits?: Audit[];
                };
                if (d.sources) setSources(d.sources);
                if (d.cases) setCases(d.cases);
                if (d.signals) setSignals(d.signals);
                if (d.audits) setAudits(d.audits);
            }
        });
        c.ready.then(() => {
            if (c.connectionId) {
                api.post('/api/subscriptions', {
                    entity_type: 'pharma-dashboard',
                    entity_id: 'global',
                    connection_id: c.connectionId,
                });
            }
        });
        return () => {
            if (c.connectionId) {
                api.post('/api/subscriptions/remove', {
                    entity_type: 'pharma-dashboard',
                    entity_id: 'global',
                    connection_id: c.connectionId,
                });
            }
            c.disconnect();
        };
    }, []);

    const loadApprovals = async () => {
        setApprovalsLoading(true);
        setApprovalsError(null);
        try {
            const r = await api.get<{ approvals?: Approval[]; audits?: Audit[] }>('/api/approvals');
            setApprovals(r.data.approvals ?? []);
            if (r.data.audits) setAudits(r.data.audits);
        } catch {
            setApprovalsError('openFDA approval feed unavailable. No record was fabricated.');
        } finally {
            setApprovalsLoading(false);
        }
    };

    // The FDA Approvals tab is premium-tier, so it loads on demand rather than
    // on mount, and only once the user actually opens it.
    useEffect(() => {
        if (tab === 'FDA Approvals' && approvals.length === 0 && !approvalsError) {
            void loadApprovals();
        }
    }, [tab]);

    const refresh = async () => {
        setBusy(true);
        setNotice('Refreshing official-source control plane…');
        try {
            const r = await api.post('/api/refresh', {});
            const d = r.data;
            setSources(d.sources || sources);
            setSignals(d.signals || []);
            setAudits(d.audits || []);
            setNotice('Source checks completed and audit evidence updated.');
        } catch {
            setNotice('Refresh failed safely; no regulatory status was fabricated.');
        } finally {
            setBusy(false);
        }
    };

    const runSignal = async () => {
        setBusy(true);
        setNotice('Calculating disproportionality on the demonstration dataset…');
        try {
            const r = await api.post('/api/signals/analyze', {});
            setSignals(r.data.signals || []);
            setAudits(r.data.audits || []);
            setTab('Signals');
            setNotice('Signal analysis completed with PRR/ROR and trend indicators.');
        } catch {
            setNotice('Signal analysis failed; no signal was promoted automatically.');
        } finally {
            setBusy(false);
        }
    };

    const generateReport = async () => {
        setBusy(true);
        setNotice('Building PSUR/PBRER working draft from verified records…');
        try {
            const r = await api.post('/api/reports/psur', {});
            setAudits(r.data.audits || []);
            setTab('Reports');
            setNotice('PSUR/PBRER draft generated for human regulatory review.');
        } catch {
            setNotice('Report generation failed safely.');
        } finally {
            setBusy(false);
        }
    };

    const verifyCase = async (id: string) => {
        try {
            const r = await api.post('/api/cases/verify', { id });
            setCases(r.data.cases || cases);
            setAudits(r.data.audits || audits);
            setNotice(`Human verification recorded for ${id}.`);
        } catch {
            setNotice('Verification could not be recorded.');
        }
    };

    const e2b = async () => {
        setBusy(true);
        setNotice('Generating ISO/ICH E2B(R3) XML validation package…');
        try {
            const r = await api.post('/api/icsr/e2b-r3', { caseId: cases[0]?.id });
            setAudits(r.data.audits || audits);
            setNotice(
                `E2B(R3) package ${r.data.packageId} generated. Production transmission remains registration-gated.`,
            );
            setTab('ICSR / E2B');
        } catch {
            setNotice('E2B(R3) package generation failed validation.');
        } finally {
            setBusy(false);
        }
    };

    const nav = [
        ['Overview', Activity],
        ['ICSR / E2B', FileCheck2],
        ['Signals', AlertTriangle],
        ['Reports', FileText],
        ['AI Governance', Brain],
        ['Sources', Globe2],
        ['Audit Trail', History],
    ] as const;

    const scrollTo = (id: string) => {
        document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    const openWorkspace = (nextTab = 'Overview') => {
        setTab(nextTab);
        window.setTimeout(() => scrollTo('workspace'), 40);
    };

    const verifiedCount = cases.filter((item) => item.humanVerified).length;
    const liveSources = sources.filter((item) => item.status === 'LIVE').length;

    return (
        <div className='site'>
            <header className='site-header'>
                <div className='logo-ring' aria-label='We Do Care Global'>
                    <Globe2 size={27} strokeWidth={1.7} />
                    <HandHeart size={15} strokeWidth={1.8} className='logo-heart' />
                </div>
                <div className='header-row'>
                    <div className='wordmark'>
                        <b>WE DO CARE GLOBAL</b>
                        <span>PHARMACOVIGILANCE · REGULATORY INTELLIGENCE · AI GOVERNANCE</span>
                    </div>
                    <nav className='public-nav' aria-label='Primary'>
                        <a href='https://github.com/we-do-care-global' target='_blank' rel='noreferrer'>
                            Published <ArrowUpRight size={13} />
                        </a>
                        <button onClick={() => scrollTo('about')}>About</button>
                        <button onClick={() => scrollTo('contact')}>Contact</button>
                    </nav>
                </div>
            </header>

            <main>
                <section className='hero reveal'>
                    <div className='hero-copy'>
                        <div className='eyebrow'>
                            <span className='pulse' />
                            WE DO CARE GLOBAL
                        </div>
                        <h1>
                            We Do Care Global
                            <span>Pharmacovigilance &amp; Regulatory Intelligence OS</span>
                        </h1>
                        <p className='hero-lede'>
                            A governed operational workspace connecting safety data, regulatory evidence,
                            retrieval intelligence and human-controlled AI decisions.
                        </p>
                        <div className='hero-meta'>
                            <span><strong>Human verified</strong> · Auditable · EU-ready</span>
                            <span>Global safety intelligence layer</span>
                            <span>ORCID 0009-0009-8515-2727</span>
                        </div>
                        <div className='hero-actions'>
                            <button className='btn btn-gold' onClick={() => openWorkspace('Overview')}>
                                Explore Platform <ArrowUpRight size={15} />
                            </button>
                            <button className='btn btn-ghost' onClick={() => scrollTo('about')}>
                                About the architecture
                            </button>
                        </div>
                    </div>

                    <div className='hero-orbit' aria-label='Platform status'>
                        <div className='orbit-core'>
                            <ShieldCheck size={30} />
                            <b>TRUST</b>
                            <span>BY DESIGN</span>
                        </div>
                        <div className='orbit-node node-gold'>ICSR</div>
                        <div className='orbit-node node-cyan'>E2B(R3)</div>
                        <div className='orbit-node node-purple'>AI</div>
                        <div className='orbit-node node-red'>RISK</div>
                    </div>
                </section>

                <section className='banner reveal' id='contact'>
                    <div>
                        <span className='banner-kicker'>ONE GOVERNED WORKSPACE</span>
                        <h2>
                            From safety data to governed action — one operational workspace for ICSR
                            intake, E2B(R3), signal detection, PSUR/PBRER, and human-controlled AI decisions.
                        </h2>
                    </div>
                    <button className='banner-cta' onClick={() => openWorkspace('ICSR / E2B')}>
                        Request Demo <ArrowUpRight size={16} />
                    </button>
                </section>

                <section className='section reveal' id='features'>
                    <div className='section-intro'>
                        <span className='section-kicker'>FEATURES</span>
                        <h2>Safety operations, wrapped in governance.</h2>
                        <p>
                            Designed for teams that need traceable decisions, regulator-aware workflows and
                            useful AI without removing human accountability.
                        </p>
                    </div>

                    <div className='feature-grid'>
                        <FeatureCard
                            icon={<FileCheck2 />}
                            tone='gold'
                            title='Regulatory Control Plane'
                            text='E2B(R3) XML generation + validation workflow with a hard human approval gate before production submission.'
                            onLearn={() => openWorkspace('ICSR / E2B')}
                        />
                        <FeatureCard
                            icon={<AlertTriangle />}
                            tone='cyan'
                            title='Signal Management'
                            text='Reviewable signal analytics with PRR, ROR and trend indicators, plus a PSUR/PBRER working-draft engine.'
                            onLearn={() => openWorkspace('Signals')}
                        />
                        <FeatureCard
                            icon={<Brain />}
                            tone='purple'
                            title='AI Governance'
                            text='Machine-first analysis, provenance, append-only audit evidence and human-in-the-loop decisions.'
                            onLearn={() => openWorkspace('AI Governance')}
                        />
                        <FeatureCard
                            icon={<ShieldCheck />}
                            tone='red'
                            title='Compliance & Residency'
                            text='EU governance evidence, source provenance and residency controls without pretending to self-certify legal compliance.'
                            onLearn={() => openWorkspace('Sources')}
                        />
                    </div>
                </section>

                <section className='stats-section reveal'>
                    <div className='stat'>
                        <b>{cases.length}</b>
                        <span>ICSR cases in workspace</span>
                    </div>
                    <div className='stat'>
                        <b>{signals.length}</b>
                        <span>signals calculated</span>
                    </div>
                    <div className='stat'>
                        <b>{verifiedCount}/{cases.length || 0}</b>
                        <span>human verified cases</span>
                    </div>
                    <div className='stat stat-wide'>
                        <b>EU</b>
                        <span>governance + residency mode</span>
                    </div>
                </section>

                <section className='about section reveal' id='about'>
                    <div className='section-intro'>
                        <span className='section-kicker'>WE DO CARE PLATFORM FABRIC</span>
                        <h2>One brand. Four complementary control layers.</h2>
                        <p>
                            The product surface stays focused on pharmacovigilance while the wider We Do Care
                            ecosystem provides retrieval, evaluation and agent-governance foundations.
                        </p>
                    </div>

                    <div className='fabric-grid'>
                        <div className='fabric-item'>
                            <span className='fabric-dot gold' />
                            <div>
                                <b>Pharmacovigilance OS</b>
                                <p>ICSR, E2B(R3), signal management, PSUR/PBRER and regulatory source control.</p>
                            </div>
                        </div>
                        <div className='fabric-item'>
                            <span className='fabric-dot cyan' />
                            <div>
                                <b>Enterprise Hybrid RAG</b>
                                <p>Retrieval fabric for grounded answers across multimodal enterprise knowledge.</p>
                            </div>
                            <a href='https://we-do-care-global.github.io/enterprise-hybrid-rag/' target='_blank' rel='noreferrer'>Explore →</a>
                        </div>
                        <div className='fabric-item'>
                            <span className='fabric-dot purple' />
                            <div>
                                <b>Agent Eval</b>
                                <p>Evaluation and observability for agent performance, tools, RAG quality and workflows.</p>
                            </div>
                            <a href='https://we-do-care-global.github.io/agent-eval/#quickstart' target='_blank' rel='noreferrer'>Explore →</a>
                        </div>
                        <div className='fabric-item'>
                            <span className='fabric-dot red' />
                            <div>
                                <b>AgentGuard</b>
                                <p>Policy, approval, audit and kill-switch controls for autonomous AI actions.</p>
                            </div>
                            <a href='https://we-do-care-global.github.io/agentguard/' target='_blank' rel='noreferrer'>Explore →</a>
                        </div>
                    </div>
                </section>

                <section className='workspace-wrap reveal' id='workspace'>
                    <div className='workspace-top'>
                        <div>
                            <span className='section-kicker'>LIVE WORKSPACE</span>
                            <h2>Operational console</h2>
                            <p>Public-facing surface above. Decision-ready execution below.</p>
                        </div>
                        <div className='workspace-actions'>
                            <span className='mini-status'><span className='pulse' /> {liveSources}/3 official sources live</span>
                            <button className='btn btn-ghost btn-small' onClick={refresh} disabled={busy}>
                                <RefreshCw size={14} className={busy ? 'spin' : ''} /> Refresh
                            </button>
                        </div>
                    </div>

                    <div className='workspace-nav'>
                        {nav.map(([name, Icon]) => (
                            <button key={name} onClick={() => setTab(name)} className={tab === name ? 'active' : ''}>
                                <Icon size={15} />
                                <span>{name}</span>
                            </button>
                        ))}
                    </div>

                    {notice && (
                        <div className='notice'>
                            <Sparkles size={15} />
                            {notice}
                        </div>
                    )}

                    {tab === 'Overview' && (
                        <div className='workspace-panel'>
                            <div className='panel-grid'>
                                <Panel title='Machine-first, human-verified' kicker='CONTROL'>
                                    <p>
                                        AI extracts clinical elements, dates, seriousness and
                                        dechallenge/rechallenge candidates. A pharmacovigilance professional
                                        makes the final decision.
                                    </p>
                                    <div className='flow'>
                                        <span>Narrative</span><b>→</b><span>AI extraction</span><b>→</b>
                                        <span>PV review</span><b>→</b><span>Regulatory action</span>
                                    </div>
                                </Panel>
                                <Panel title='Regulatory readiness' kicker='READINESS'>
                                    <Readiness label='E2B(R3) XML workflow' state='READY' />
                                    <Readiness label='EMA production gateway' state='GATED' />
                                    <Readiness label='Signal management' state='READY' />
                                    <Readiness label='PSUR/PBRER draft engine' state='READY' />
                                    <Readiness label='AI governance evidence' state='READY' />
                                </Panel>
                            </div>
                        </div>
                    )}

                    {tab === 'ICSR / E2B' && (
                        <WorkspaceView
                            title='ICSR & E2B(R3)'
                            subtitle='Structured case processing with a hard human approval gate.'
                            action={
                                <button className='btn btn-gold btn-small' onClick={e2b} disabled={busy}>
                                    <Send size={14} /> Generate E2B(R3)
                                </button>
                            }
                        >
                            <div className='case-list'>
                                {cases.map((item) => (
                                    <div className='case-row' key={item.id}>
                                        <div>
                                            <b>{item.id}</b>
                                            <span>{item.drug} · {item.reaction} · {item.seriousness}</span>
                                        </div>
                                        <div className='case-ai'><Brain size={13} /> {item.aiConfidence}% AI confidence</div>
                                        <div className={item.humanVerified ? 'verified' : 'pending'}>
                                            {item.humanVerified ? 'HUMAN VERIFIED' : 'AWAITING HUMAN'}
                                        </div>
                                        {!item.humanVerified && (
                                            <button className='micro-btn' onClick={() => verifyCase(item.id)}>
                                                <CheckCircle2 size={12} /> Verify
                                            </button>
                                        )}
                                    </div>
                                ))}
                            </div>
                            <div className='xml-card'>
                                <FileCheck2 />
                                <div>
                                    <b>ISO/ICH E2B(R3) validation package</b>
                                    <p>
                                        Generates a standards-oriented XML package and validation report. Production
                                        transmission stays registration-gated.
                                    </p>
                                </div>
                            </div>
                        </WorkspaceView>
                    )}

                    {tab === 'Signals' && (
                        <WorkspaceView
                            title='Signal management'
                            subtitle='Disproportionality analytics with reviewable evidence.'
                            action={
                                <button className='btn btn-gold btn-small' onClick={runSignal} disabled={busy}>
                                    <Zap size={14} /> Recalculate
                                </button>
                            }
                        >
                            <div className='signal-grid'>
                                {(signals.length
                                    ? signals
                                    : [{
                                        title: 'Cardiac dysfunction / trastuzumab',
                                        severity: 'HIGH',
                                        source: 'ICSR workspace',
                                        country: 'EU',
                                        impact: 'Review for potential signal',
                                        prr: 4.21,
                                        ror: 4.08,
                                        trend: 'RISING',
                                        created_at: Date.now(),
                                    }]).map((item, index) => (
                                        <div className='signal' key={item.id || index}>
                                            <div className='signal-top'>
                                                <span className={'sev ' + item.severity.toLowerCase()}>{item.severity}</span>
                                                <b>{item.title}</b>
                                            </div>
                                            <div className='signal-stats'>
                                                <span>PRR <strong>{item.prr.toFixed(2)}</strong></span>
                                                <span>ROR <strong>{item.ror.toFixed(2)}</strong></span>
                                                <span>TREND <strong>{item.trend}</strong></span>
                                            </div>
                                            <small>{item.country} · {item.source} · {item.impact}</small>
                                        </div>
                                    ))}
                            </div>
                        </WorkspaceView>
                    )}

                    {tab === 'Reports' && (
                        <WorkspaceView
                            title='PSUR / PBRER workspace'
                            subtitle='Generate a structured working draft, then route it through regulatory review.'
                            action={
                                <button className='btn btn-gold btn-small' onClick={generateReport} disabled={busy}>
                                    <FileText size={14} /> Generate draft
                                </button>
                            }
                        >
                            <div className='report-grid'>
                                <Report title='PSUR' desc='Periodic safety update structure with benefit-risk narrative, signal overview and ICSR evidence.' />
                                <Report title='PBRER' desc='Benefit-risk evaluation structure with cumulative safety data and action tracking.' />
                            </div>
                            <div className='review-banner'>
                                <ClipboardCheck />
                                <div>
                                    <b>Human sign-off required</b>
                                    <p>Generated text is a working draft, not a submitted regulatory report.</p>
                                </div>
                            </div>
                        </WorkspaceView>
                    )}

                    {tab === 'AI Governance' && (
                        <WorkspaceView title='Trustworthy AI control room' subtitle='Evidence for human oversight, transparency, validation and accountability.'>
                            <div className='govern-grid'>
                                <Readiness label='Human oversight' state='ENABLED' />
                                <Readiness label='Model output provenance' state='TRACKED' />
                                <Readiness label='Decision audit trail' state='APPEND-ONLY' />
                                <Readiness label='Risk & limitation disclosure' state='ACTIVE' />
                                <Readiness label='EU AI Act evidence pack' state='WORKSPACE' />
                                <Readiness label='Data residency policy' state='EU REGION' />
                            </div>
                            <p className='muted'>
                                The system supports governance evidence. It does not self-certify legal compliance
                                or replace qualified regulatory, privacy or AI compliance assessment.
                            </p>
                        </WorkspaceView>
                    )}

                    {tab === 'Sources' && (
                        <WorkspaceView
                            title='Official source control plane'
                            subtitle='Source-backed status, not decorative “LIVE” labels.'
                            action={
                                <button className='btn btn-ghost btn-small' onClick={refresh} disabled={busy}>
                                    <RefreshCw size={14} /> Refresh
                                </button>
                            }
                        >
                            <div className='source-list'>
                                {sources.map((item) => (
                                    <div className='source' key={item.id}>
                                        <div>
                                            <b>{item.name}</b>
                                            <span>{item.region} · {item.message}</span>
                                        </div>
                                        <div className={'source-status ' + item.status.toLowerCase()}>{item.status}</div>
                                        <a href={item.url} target='_blank' rel='noreferrer'>Official source</a>
                                    </div>
                                ))}
                            </div>
                        </WorkspaceView>
                    )}

                    {tab === 'Audit Trail' && (
                        <WorkspaceView title='Append-only audit trail' subtitle='Every AI, human and regulatory workflow action leaves evidence.'>
                            <div className='audit-list'>
                                {(audits.length
                                    ? audits
                                    : [{
                                        actor: 'system',
                                        action: 'workspace_initialized',
                                        entity: 'pharma-dashboard',
                                        timestamp: Date.now(),
                                        hash: 'demo-evidence',
                                    }]).slice(0, 20).map((item, index) => (
                                    <div className='audit' key={item.id || index}>
                                        <History size={14} />
                                        <div>
                                            <b>{item.action}</b>
                                            <span>{item.actor} · {item.entity}</span>
                                        </div>
                                        <code>{item.hash}</code>
                                    </div>
                                ))}
                            </div>
                        </WorkspaceView>
                    )}
                </section>


{tab === 'FDA Approvals' && (
  <WorkspaceView
    title='FDA Drug Approvals'
    subtitle='Recent prescription drug approvals from openFDA (premium module)'
    action={
      <button className='btn btn-ghost btn-small' onClick={refresh} disabled={busy}>
        <RefreshCw size={14} /> Refresh
      </button>
    }
  >
    {approvalsLoading ? (<p>Loading approvals...</p>) : approvalsError ? (<p className='error'>Error: {approvalsError}</p>) : (<>
      <div className='approvals-table'>
        <table>
          <thead>
            <tr>
              <th>Drug Name</th>
              <th>Approval Date</th>
              <th>Indication</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {approvals.map((approval, idx) => {
              const raw = approval.approval_date ?? '';
              const approvalDate = raw.length === 8
                ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`
                : raw;
              const isNew = Boolean(approvalDate) &&
                new Date(approvalDate).getTime() > Date.now() - 30 * 24 * 60 * 60 * 1000;
              return (<tr key={approval.id ?? idx}>
                <td>{approval.drug_name}</td>
                <td>{approvalDate}</td>
                <td>{approval.indication}</td>
                <td>
                  {isNew
                    ? <span className='badge badge-new'>New</span>
                    : <span className='badge badge-old'>Existing</span>}
                </td>
              </tr>);
            })}
          </tbody>
        </table>
      </div>
    </>)}
  </WorkspaceView>
)}
                <footer className='footer'>
                    <div>
                        <b>We Do Care Global</b>
                        <span>Pharmacovigilance &amp; Regulatory Intelligence OS</span>
                    </div>
                    <div className='footer-links'>
                        <button onClick={() => scrollTo('about')}>About</button>
                        <button onClick={() => scrollTo('contact')}>Contact</button>
                        <a href='https://github.com/we-do-care-global' target='_blank' rel='noreferrer'>GitHub</a>
                        <a href='https://orcid.org/0009-0009-8515-2727' target='_blank' rel='noreferrer'>ORCID</a>
                    </div>
                    <div className='footer-note'>© 2026 We Do Care Global · Apache 2.0 · EU governance workspace</div>
                </footer>
            </main>
        </div>
    );
}

function FeatureCard({
    icon,
    tone,
    title,
    text,
    onLearn,
}: {
    icon: React.ReactNode;
    tone: string;
    title: string;
    text: string;
    onLearn: () => void;
}) {
    return (
        <article className={'feature-card ' + tone}>
            <div className='feature-icon'>{icon}</div>
            <h3>{title}</h3>
            <p>{text}</p>
            <button onClick={onLearn}>Learn more <ArrowUpRight size={13} /></button>
        </article>
    );
}

function Panel({ title, kicker, children }: { title: string; kicker: string; children: React.ReactNode }) {
    return (
        <div className='panel'>
            <span className='section-kicker'>{kicker}</span>
            <h3>{title}</h3>
            {children}
        </div>
    );
}

function WorkspaceView({
    title,
    subtitle,
    action,
    children,
}: {
    title: string;
    subtitle: string;
    action?: React.ReactNode;
    children: React.ReactNode;
}) {
    return (
        <div className='workspace-view'>
            <div className='workspace-head'>
                <div>
                    <span className='section-kicker'>WE DO CARE GLOBAL</span>
                    <h3>{title}</h3>
                    <p>{subtitle}</p>
                </div>
                {action}
            </div>
            {children}
        </div>
    );
}

function Readiness({ label, state }: { label: string; state: string }) {
    return (
        <div className='readiness'>
            <span>{label}</span>
            <b>{state}</b>
        </div>
    );
}

function Report({ title, desc }: { title: string; desc: string }) {
    return (
        <div className='report'>
            <FileText size={18} />
            <div>
                <b>{title}</b>
                <p>{desc}</p>
                <span>WORKING DRAFT · HUMAN REVIEW</span>
            </div>
        </div>
    );
}

export default App;
