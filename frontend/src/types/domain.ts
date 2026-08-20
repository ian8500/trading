export type Severity = "healthy" | "warning" | "critical" | "neutral";
export type Direction = "LONG" | "SHORT";
export type OpportunityStatus = "ELIGIBLE" | "REJECTED" | "BELOW_THRESHOLD" | "OBSERVATION_ONLY";
export type MarketRegime =
  | "TRENDING_UP"
  | "TRENDING_DOWN"
  | "RANGING"
  | "HIGH_VOLATILITY"
  | "LOW_VOLATILITY"
  | "RISK_ON"
  | "RISK_OFF"
  | "UNKNOWN";

export interface SeriesPoint {
  timestamp: string;
  value: number;
  secondary?: number;
  tertiary?: number;
}

export interface ChartMarker {
  id: string;
  timestamp: string;
  value: number;
  direction: Direction;
  label: string;
  positive: boolean;
}

export interface OpportunityFactor {
  label: string;
  value: number;
  contribution: number;
  tone: "positive" | "negative" | "neutral";
  detail: string;
}

export interface Opportunity {
  id: string;
  timestamp: string;
  instrument: string;
  marketFamily: "FX" | "INDEX" | "COMMODITY" | "CRYPTO" | "EQUITY";
  direction: Direction;
  strategy: string;
  strategyVersion: string;
  score: number;
  originalScore: number;
  status: OpportunityStatus;
  signalPrice: number;
  expectedHorizon: string;
  calibratedProbability: number | null;
  expectedUpside: number;
  expectedDownside: number;
  rewardRiskRatio: number;
  estimatedTotalCost: number;
  regime: MarketRegime;
  factors: OpportunityFactor[];
  explanation: string;
  rejectionReasons: string[];
  approvedByChallenger: boolean;
  riskDecision: "APPROVED" | "REJECTED" | "NOT_EVALUATED";
  proposedRisk: number;
}

export interface Position {
  id: string;
  instrument: string;
  direction: Direction;
  strategy: string;
  openedAt: string;
  entryPrice: number;
  currentPrice: number;
  stopPrice: number;
  targetPrice: number;
  size: number;
  currency: string;
  marginUsed: number;
  plannedRisk: number;
  unrealisedPnl: number;
  unrealisedPercent: number;
  regime: MarketRegime;
  source: "SIMULATED" | "IG_DEMO";
}

export interface Trade {
  id: string;
  instrument: string;
  direction: Direction;
  strategy: string;
  strategyVersion: string;
  openedAt: string;
  closedAt: string;
  entryPrice: number;
  exitPrice: number;
  stopPrice: number;
  targetPrice: number;
  size: number;
  grossPnl: number;
  netPnl: number;
  costs: {
    spread: number;
    slippage: number;
    financing: number;
    commission: number;
  };
  opportunityScore: number;
  challengeResult: string;
  riskDecision: string;
  explanation: string;
  exitReason: string;
  regime: MarketRegime;
  managedEquityBefore: number;
  managedEquityAfter: number;
  mae: number;
  mfe: number;
}

export interface StrategyHealth {
  id: string;
  name: string;
  state: "NORMAL" | "REDUCED_RISK" | "SUSPENDED" | "OBSERVATION_ONLY";
  expectancy: number;
  winRate: number;
  profitFactor: number;
  drawdown: number;
  sampleSize: number;
  updatedAt: string;
}

export interface MarketEvent {
  id: string;
  scheduledAt: string;
  country: string;
  currency: string;
  name: string;
  type: "MACRO" | "CENTRAL_BANK" | "NEWS" | "MARKET";
  importance: "LOW" | "MEDIUM" | "HIGH";
  state: "NORMAL" | "PRE_EVENT" | "RELEASE_WINDOW" | "POST_EVENT";
  forecast?: string;
  actual?: string;
  previous?: string;
  surprise?: number;
  source: string;
  sourceUrl?: string;
  affectedMarkets: string[];
  summary: string;
  receivedAt: string;
}

export interface ServiceHealth {
  id: string;
  name: string;
  status: Severity;
  message: string;
  checkedAt: string;
  latencyMs?: number;
}

export interface AuditEvent {
  id: string;
  timestamp: string;
  category: "CONTROL" | "RISK" | "BROKER" | "DATA" | "STRATEGY" | "SYSTEM";
  summary: string;
  detail: string;
  severity: Severity;
  actor: string;
}

export interface DashboardSnapshot {
  asOf: string;
  mode: "HISTORICAL" | "REPLAY" | "IG_DEMO";
  startingCapital: number;
  managedEquity: number;
  brokerDemoBalance: number | null;
  returnPercent: number;
  target: number;
  maxDrawdown: number;
  openRisk: number;
  autonomousDemo: boolean;
  circuitBreakers: "HEALTHY" | "BLOCKED";
  equityCurve: SeriesPoint[];
  drawdownCurve: SeriesPoint[];
  exposureCurve: SeriesPoint[];
  opportunities: Opportunity[];
  positions: Position[];
  recentTrades: Trade[];
  rejectedOpportunities: Opportunity[];
  strategyHealth: StrategyHealth[];
  events: MarketEvent[];
  services: ServiceHealth[];
}

export interface AutopilotStrategyStatus {
  name: string;
  status: "NOT_ELIGIBLE" | "RESEARCH_GATES_PASSED_PROMOTION_BLOCKED";
  returnPercent: number;
  profitFactor: number;
  trades: number;
  maximumDrawdownPercent: number;
  unmetGateCount: number;
}

export interface AutopilotSnapshot {
  mode: "SAFE_RESEARCH_AUTOPILOT";
  state: "STAY_IN_CASH" | "HUMAN_REVIEW_REQUIRED";
  headline: string;
  summary: string;
  checkedAt: string;
  nextCheckAt: string;
  refreshSeconds: number;
  automaticMonitoring: boolean;
  evidenceStatus: "VERIFIED" | "MISSING" | "INVALID";
  evidenceGeneratedAt: string | null;
  protocolVersion: string;
  protocolFingerprint: string;
  reportFingerprint: string | null;
  implementationDigest: string;
  strategies: AutopilotStrategyStatus[];
  reasons: string[];
  safeguards: string[];
  demoTradingEnabled: boolean;
  liveTradingEnabled: boolean;
  orderExecutionEnabled: boolean;
}

export interface BacktestMetrics {
  startingEquity: number;
  finalEquity: number;
  totalReturn: number;
  cagr: number;
  maximumDrawdown: number;
  drawdownDuration: string;
  trades: number;
  winRate: number;
  averageWinner: number;
  averageLoser: number;
  profitFactor: number;
  expectancy: number;
  sharpe: number;
  sortino: number;
  calmar: number;
  exposure: number;
  averageLeverage: number;
  maxLeverage: number;
  totalCosts: number;
}

export interface BreakdownRow {
  label: string;
  trades: number;
  returnPercent: number;
  pnl: number;
  winRate: number;
}

export interface MonthlyReturn {
  period: string;
  value: number;
}

export interface MonteCarloResult {
  percentile5: number;
  percentile25: number;
  median: number;
  percentile75: number;
  percentile95: number;
  belowStartingProbability: number;
  ruinProbability: number;
  target750Probability: number;
  target1000Probability: number;
  target5000Probability: number;
}

export interface BacktestResult {
  id: string;
  name: string;
  status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  progress: number;
  createdAt: string;
  startedAt: string;
  completedAt?: string;
  dataSource: string;
  dataQuality: string;
  symbols: string[];
  dateFrom: string;
  dateTo: string;
  resolution: string;
  strategy: string;
  riskProfile: string;
  costModel: string;
  compounding: boolean;
  riskTaper: boolean;
  seed: number;
  metrics: BacktestMetrics;
  equityCurve: SeriesPoint[];
  drawdownCurve: SeriesPoint[];
  exposureCurve: SeriesPoint[];
  trades: Trade[];
  rejectedOpportunities: Opportunity[];
  monthlyReturns: MonthlyReturn[];
  annualReturns: MonthlyReturn[];
  instrumentBreakdown: BreakdownRow[];
  regimeBreakdown: BreakdownRow[];
  strategyBreakdown: BreakdownRow[];
  monteCarlo: MonteCarloResult;
  milestones: Record<string, string | null>;
}

export interface BacktestRequest {
  dateFrom: string;
  dateTo: string;
  startingCapital: number;
  instruments: string[];
  strategies: string[];
  riskProfile: string;
  costModel: string;
  resolution: string;
  compounding: boolean;
  riskTaper: boolean;
}

export interface ReplayTick {
  timestamp: string;
  prices: Record<string, number>;
  regime: MarketRegime;
  managedEquity: number;
  unrealisedPnl: number;
  opportunity?: Opportunity;
  event?: MarketEvent;
  position?: Position;
  circuitBreaker?: string;
}

export interface ReplaySession {
  id: string;
  status: "READY" | "RUNNING" | "PAUSED" | "COMPLETED";
  dateFrom: string;
  dateTo: string;
  strategy: string;
  riskProfile: string;
  costModel: string;
  startingCapital: number;
  ticks: ReplayTick[];
}

export interface StrategyVersion {
  id: string;
  name: string;
  version: string;
  role: "CHAMPION" | "CHALLENGER";
  family: string;
  state: StrategyHealth["state"];
  createdAt: string;
  immutable: boolean;
  parameters: Record<string, string | number | boolean>;
  dataRange: string;
  historical: { returnPercent: number; sharpe: number; drawdown: number; trades: number };
  outOfSample: { returnPercent: number; sharpe: number; degradation: number };
  demo: { returnPercent: number; trades: number; durationDays: number };
  promotionState: "APPROVED" | "IN_REVIEW" | "NOT_ELIGIBLE";
  parameterSurface: number[][];
}

export interface BrokerMarket {
  epic: string;
  instrument: string;
  type: string;
  status: string;
  snapshot: boolean;
  streaming: boolean;
  historical: boolean;
  minDealSize: number;
  marginFactor: number;
  controlledRisk: boolean;
  tradeableForManagedCapital: boolean;
  rejectionReason?: string;
}

export interface BrokerConfirmation {
  id: string;
  timestamp: string;
  dealReference: string;
  status: "ACCEPTED" | "REJECTED" | "PENDING";
  summary: string;
}

export interface IgDemoStatus {
  configured: boolean;
  connected: boolean;
  accountIdMasked: string;
  brokerBalance: number | null;
  managedEquity: number;
  availableFunds: number | null;
  streamStatus: "CONNECTED" | "DISCONNECTED" | "NOT_CONFIGURED";
  reconciliation: "RECONCILED" | "RECONCILIATION_REQUIRED" | "NOT_CONNECTED";
  autonomousMode: boolean;
  newTradesAllowed: boolean;
  lastReconciledAt?: string;
  positions: Position[];
  pendingOrders: number;
  confirmations: BrokerConfirmation[];
  markets: BrokerMarket[];
}

export interface RiskStatus {
  profile: "Conservative" | "Standard" | "Aggressive" | "Experimental" | "Custom";
  managedEquity: number;
  riskPerTrade: number;
  maxOpenRisk: number;
  currentOpenRisk: number;
  marginUsage: number;
  effectiveLeverage: number;
  dailyPnl: number;
  weeklyPnl: number;
  drawdown: number;
  taperEnabled: boolean;
  circuitBreakers: Array<{ name: string; status: Severity; threshold: string; current: string; detail: string }>;
  correlationExposure: Array<{ cluster: string; exposure: number; limit: number }>;
  blockedStrategies: string[];
  blockedMarkets: string[];
}

export interface ReadinessCheck {
  id: string;
  label: string;
  status: "PASS" | "WARN" | "FAIL" | "PENDING";
  value: string;
  requirement: string;
  evidence: string;
  checkedAt: string;
}

export interface LiveReadiness {
  status: "NOT_ELIGIBLE" | "ELIGIBLE_FOR_MANUAL_REVIEW";
  liveExecutionEnabled: false;
  evaluatedAt: string;
  checks: ReadinessCheck[];
}

export interface SystemSnapshot {
  asOf: string;
  services: ServiceHealth[];
  auditEvents: AuditEvent[];
  environment: {
    appVersion: string;
    appEnvironment: string;
    timezone: string;
    database: string;
    aiProvider: string;
    liveExecution: string;
  };
}
