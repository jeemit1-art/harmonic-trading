"""
Data fetching layer. Uses yfinance (free) as the default source across all
four markets. Swap in a broker feed later by writing another class with the
same `.fetch(ticker, interval, period)` interface -- nothing else in the
system needs to change.
"""
import pandas as pd
import time

try:
    import yfinance as yf
except ImportError:
    yf = None


class YFinanceSource:
    """
    Ticker suffix cheat-sheet (yfinance / Yahoo Finance convention):
        AUS (ASX)  -> 'BHP.AX', 'CBA.AX', 'CSL.AX' ...
        US         -> 'AAPL', 'MSFT', 'SPY' ...
        India      -> 'RELIANCE.NS', 'TCS.NS', 'INFY.NS' (NSE) or '.BO' for BSE
        Forex      -> 'AUDUSD=X', 'EURUSD=X', 'USDJPY=X', 'GBPUSD=X' ...
    """
    name = "yfinance"

    def fetch(self, ticker: str, interval: str = "1h", period: str = "60d",
              retries: int = 3) -> pd.DataFrame:
        if yf is None:
            raise RuntimeError("yfinance not installed. Run: pip install yfinance")

        # yfinance limits how far back intraday intervals go; clamp sensibly
        intraday_caps = {"1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d",
                          "1h": "730d", "60m": "730d"}
        if interval in intraday_caps:
            max_period = intraday_caps[interval]
            period = max_period if period == "max" else period

        last_err = None
        for attempt in range(retries):
            try:
                df = yf.download(ticker, interval=interval, period=period,
                                  progress=False, auto_adjust=True)
                if df is None or df.empty:
                    raise ValueError(f"No data returned for {ticker}")
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
                return df
            except Exception as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Failed to fetch {ticker} after {retries} attempts: {last_err}")


DEFAULT_SOURCE = YFinanceSource()


# --------------------------------------------------------------------------
# Watchlists -- edit freely. Kept small & liquid by default; liquid names
# form cleaner, more reliable harmonic structures than thin/illiquid ones.
# --------------------------------------------------------------------------

WATCHLISTS = {
    # ~180 ASX-listed companies, cleaned from the S&P/ASX 200 constituent
    # list -- ETF/fund tickers removed (not individual companies), and
    # several since-delisted/merged names removed (Afterpay, Newcrest,
    # OZ Minerals, Sydney Airport, Crown Resorts, Allkem) or corrected
    # (Woodside Petroleum WPL -> Woodside Energy WDS after its 2022
    # merger). Source list dated Jan 2022; if any individual ticker below
    # has since delisted or changed symbol, the scanner logs and skips it
    # gracefully -- it won't break the rest of the scan.
    "AUS": [
        "ABP.AX","AGL.AX","ALQ.AX","ALU.AX","AWC.AX","AMC.AX","AMP.AX","ALD.AX",
        "ANN.AX","APA.AX","APM.AX","ARB.AX","ARG.AX","ALL.AX","ASX.AX","ALX.AX",
        "AIA.AX","AZJ.AX","ANZ.AX","AFI.AX","BOQ.AX","BAP.AX","BPT.AX","BEN.AX",
        "BHP.AX","BSL.AX","BLD.AX","BXB.AX","BRG.AX","BKW.AX","BWP.AX","CAR.AX",
        "CNI.AX","CIP.AX","CHN.AX","CGF.AX","CIA.AX","CHC.AX","CLW.AX","CQR.AX",
        "CNU.AX","CIM.AX","CWY.AX","COH.AX","COL.AX","CBA.AX","CPU.AX","CRN.AX",
        "CTD.AX","CCP.AX","CMW.AX","CSL.AX","CSR.AX","DRR.AX","DXS.AX","DDR.AX",
        "DHG.AX","DMP.AX","DOW.AX","APE.AX","EBO.AX","EDV.AX","EVT.AX","EVN.AX",
        "FPH.AX","FBU.AX","FLT.AX","FMG.AX","GNE.AX","GMG.AX","GPT.AX","GQG.AX",
        "GOZ.AX","HVN.AX","HLS.AX","HMC.AX","IEL.AX","IGO.AX","ILU.AX","IMU.AX",
        "IPL.AX","IFT.AX","INA.AX","IFL.AX","IAG.AX","IRE.AX","JHX.AX","JBH.AX",
        "JLG.AX","JDO.AX","LFS.AX","LLC.AX","LNK.AX","LTR.AX","LYC.AX","MQG.AX",
        "MFG.AX","MPL.AX","MP1.AX","MCY.AX","MEZ.AX","MTS.AX","MIN.AX","MGR.AX",
        "NAB.AX","NSR.AX","NWL.AX","NXT.AX","NHF.AX","NIC.AX","NEC.AX","NST.AX",
        "NVX.AX","ORI.AX","ORG.AX","ORA.AX","PDN.AX","PDL.AX","PXA.AX","PLS.AX",
        "PNI.AX","PMV.AX","PME.AX","QAN.AX","QBE.AX","QUB.AX","RHC.AX","REA.AX",
        "REH.AX","RWC.AX","RMD.AX","RIO.AX","SFR.AX","STO.AX","SCG.AX","SEK.AX",
        "SVW.AX","SCP.AX","SGM.AX","SKC.AX","SHL.AX","S32.AX","SPK.AX","SDF.AX",
        "SGP.AX","SNZ.AX","SUN.AX","SUL.AX","TAH.AX","TNE.AX","TLX.AX","TLS.AX",
        "A2M.AX","SGR.AX","TPG.AX","TCL.AX","TWE.AX","UWL.AX","VCX.AX","VUK.AX",
        "VEA.AX","SOL.AX","WES.AX","WBC.AX","WHC.AX","WTC.AX","WDS.AX","WOW.AX",
        "WOR.AX","XRO.AX","YAL.AX","ZIM.AX","Z1P.AX",
    ],

    # Full S&P 500 constituent list (503 tickers incl. dual share classes),
    # sourced from Wikipedia's "List of S&P 500 companies" (current as of
    # this build). Note BRK.B/BF.B use yfinance's hyphen convention
    # (BRK-B, BF-B), not the period used in official ticker notation.
    "US": [
        "MMM","AOS","ABT","ABBV","ACN","ADBE","AMD","AES","AFL","A","APD","ABNB",
        "AKAM","ALB","ARE","ALGN","ALLE","LNT","ALL","GOOGL","GOOG","MO","AMZN",
        "AMCR","AEE","AEP","AXP","AIG","AMT","AWK","AMP","AME","AMGN","APH","ADI",
        "AON","APA","APO","AAPL","AMAT","APP","APTV","ACGL","ADM","ARES","ANET",
        "AJG","AIZ","T","ATO","ADSK","ADP","AZO","AVB","AVY","AXON","BKR","BALL",
        "BAC","BAX","BDX","BRK-B","BBY","TECH","BIIB","BLK","BX","XYZ","BNY","BA",
        "BKNG","BSX","BMY","AVGO","BR","BRO","BF-B","BLDR","BG","BXP","CHRW","CDNS",
        "CPT","CPB","COF","CAH","CCL","CARR","CVNA","CASY","CAT","CBOE","CBRE",
        "CDW","COR","CNC","CNP","CF","CRL","SCHW","CHTR","CVX","CMG","CB","CHD",
        "CIEN","CI","CINF","CTAS","CSCO","C","CFG","CLX","CME","CMS","KO","CTSH",
        "COHR","COIN","CL","CMCSA","FIX","CAG","COP","ED","STZ","CEG","COO","CPRT",
        "GLW","CPAY","CTVA","CSGP","COST","CRH","CRWD","CCI","CSX","CMI","CVS",
        "DHR","DRI","DDOG","DVA","DECK","DE","DELL","DAL","DVN","DXCM","FANG","DLR",
        "DG","DLTR","D","DPZ","DASH","DOV","DOW","DHI","DTE","DUK","DD","ETN",
        "EBAY","SATS","ECL","EIX","EW","EA","ELV","EME","EMR","ETR","EOG","EPAM",
        "EQT","EFX","EQIX","EQR","ERIE","ESS","EL","EG","EVRG","ES","EXC","EXE",
        "EXPE","EXPD","EXR","XOM","FFIV","FDS","FICO","FAST","FRT","FDX","FIS",
        "FITB","FSLR","FE","FISV","F","FTNT","FTV","FOXA","FOX","BEN","FCX","GRMN",
        "IT","GE","GEHC","GEV","GEN","GNRC","GD","GIS","GM","GPC","GILD","GPN",
        "GL","GDDY","GS","HAL","HIG","HAS","HCA","DOC","HSIC","HSY","HPE","HLT",
        "HD","HON","HRL","HST","HWM","HPQ","HUBB","HUM","HBAN","HII","IBM","IEX",
        "IDXX","ITW","INCY","IR","PODD","INTC","IBKR","ICE","IFF","IP","INTU",
        "ISRG","IVZ","INVH","IQV","IRM","JBHT","JBL","JKHY","J","JNJ","JCI","JPM",
        "KVUE","KDP","KEY","KEYS","KMB","KIM","KMI","KKR","KLAC","KHC","KR","LHX",
        "LH","LRCX","LVS","LDOS","LEN","LII","LLY","LIN","LYV","LMT","L","LOW",
        "LULU","LITE","LYB","MTB","MPC","MAR","MMC","MLM","MAS","MA","MKC","MCD",
        "MCK","MDT","MRK","META","MET","MTD","MGM","MCHP","MU","MSFT","MAA","MRNA",
        "TAP","MDLZ","MPWR","MNST","MCO","MS","MOS","MSI","MSCI","NDAQ","NTAP",
        "NFLX","NEM","NWSA","NWS","NEE","NKE","NI","NDSN","NSC","NTRS","NOC","NCLH",
        "NRG","NUE","NVDA","NVR","NXPI","ORLY","OXY","ODFL","OMC","ON","OKE","ORCL",
        "OTIS","PCAR","PKG","PLTR","PANW","PSKY","PH","PAYX","PYPL","PNR","PEP",
        "PFE","PCG","PM","PSX","PNW","PNC","POOL","PPG","PPL","PFG","PG","PGR",
        "PLD","PRU","PEG","PTC","PSA","PHM","PWR","QCOM","DGX","RL","RJF","RTX",
        "O","REG","REGN","RF","RSG","RMD","RVTY","HOOD","ROK","ROL","ROP","ROST",
        "RCL","SPGI","CRM","SNDK","SBAC","SLB","STX","SRE","NOW","SHW","SPG","SWKS",
        "SJM","SW","SNA","SOLV","SO","LUV","SWK","SBUX","STT","STLD","STE","SYK",
        "SMCI","SYF","SNPS","SYY","TMUS","TROW","TTWO","TPR","TRGP","TGT","TEL",
        "TDY","TER","TSLA","TXN","TPL","TXT","TMO","TJX","TKO","TTD","TSCO","TT",
        "TDG","TRV","TRMB","TFC","TYL","TSN","USB","UBER","UDR","ULTA","UNP","UAL",
        "UPS","URI","UNH","UHS","VLO","VEEV","VTR","VLTO","VRSN","VRSK","VZ","VRTX",
        "VRT","VTRS","VICI","V","VST","VMC","WRB","GWW","WAB","WMT","DIS","WBD",
        "WM","WAT","WEC","WFC","WELL","WST","WDC","WY","WSM","WMB","WTW","WDAY",
        "WYNN","XEL","XYL","YUM","ZBRA","ZBH","ZTS",
    ],

    # Nifty 500 constituent list, sourced from a public NSE-tracking CSV
    # (github.com/kprohith/nse-stock-analysis). I cross-checked it against
    # known corporate actions and removed 10 entries confirmed stale --
    # PSU banks merged in the 2019-2020 mega-merger (Allahabad Bank, Andhra
    # Bank, Corporation Bank, Oriental Bank of Commerce, Syndicate Bank all
    # absorbed into other banks) plus companies that went through insolvency
    # around the same period (DHFL, Jet Airways, Reliance Capital, Reliance
    # Communications) and Adani Transmission (renamed Adani Energy Solutions).
    # TATAMOTORS corrected to TMPV per the earlier fix. As always, if any
    # remaining ticker has since delisted or changed symbol, the scanner logs
    # it and skips to the next one rather than breaking the whole run.
    "INDIA": [
        "3MINDIA.NS", "ABB.NS", "ACC.NS", "AIAENG.NS",
        "APLAPOLLO.NS", "AUBANK.NS", "AAVAS.NS", "ADANIGREEN.NS",
        "ADANIPORTS.NS", "ADANIPOWER.NS", "ABCAPITAL.NS", "ABFRL.NS",
        "ADVENZYMES.NS", "AEGISCHEM.NS", "AJANTPHARM.NS", "AKZOINDIA.NS",
        "APLLTD.NS", "ALKEM.NS", "ALLCARGO.NS", "AMARAJABAT.NS",
        "AMBUJACEM.NS", "APOLLOHOSP.NS", "APOLLOTYRE.NS", "ASHOKLEY.NS",
        "ASHOKA.NS", "ASIANPAINT.NS", "ASTERDM.NS", "ASTRAZEN.NS",
        "ASTRAL.NS", "ATUL.NS", "AUROPHARMA.NS", "AVANTIFEED.NS",
        "DMART.NS", "AXISBANK.NS", "BASF.NS", "BEML.NS",
        "BSE.NS", "BAJAJ-AUTO.NS", "BAJAJCON.NS", "BAJAJELEC.NS",
        "BAJFINANCE.NS", "BAJAJFINSV.NS", "BAJAJHLDNG.NS", "BALKRISIND.NS",
        "BALMLAWRIE.NS", "BALRAMCHIN.NS", "BANDHANBNK.NS", "BANKBARODA.NS",
        "BANKINDIA.NS", "MAHABANK.NS", "BATAINDIA.NS", "BERGEPAINT.NS",
        "BDL.NS", "BEL.NS", "BHARATFORG.NS", "BHEL.NS",
        "BPCL.NS", "BHARTIARTL.NS", "INFRATEL.NS", "BIOCON.NS",
        "BIRLACORPN.NS", "BLISSGVS.NS", "BLUEDART.NS", "BLUESTARCO.NS",
        "BBTC.NS", "BOMDYEING.NS", "BOSCHLTD.NS", "BRIGADE.NS",
        "BRITANNIA.NS", "CARERATING.NS", "CCL.NS", "CESC.NS",
        "CGPOWER.NS", "CRISIL.NS", "CADILAHC.NS", "CANFINHOME.NS",
        "CANBK.NS", "CAPLIPOINT.NS", "CARBORUNIV.NS", "CASTROLIND.NS",
        "CEATLTD.NS", "CENTRALBK.NS", "CDSL.NS", "CENTURYPLY.NS",
        "CERA.NS", "CHAMBLFERT.NS", "CHENNPETRO.NS", "CHOLAHLDNG.NS",
        "CHOLAFIN.NS", "CIPLA.NS", "CUB.NS", "COALINDIA.NS",
        "COCHINSHIP.NS", "COFFEEDAY.NS", "COLPAL.NS", "CONCOR.NS",
        "COROMANDEL.NS", "COX&KINGS.NS", "CREDITACC.NS", "CROMPTON.NS",
        "CUMMINSIND.NS", "CYIENT.NS", "DBCORP.NS", "DCBBANK.NS",
        "DCMSHRIRAM.NS", "DLF.NS", "DABUR.NS", "DEEPAKFERT.NS",
        "DEEPAKNTR.NS", "DELTACORP.NS", "DBL.NS", "DISHTV.NS",
        "DCAL.NS", "DIVISLAB.NS", "DIXON.NS", "LALPATHLAB.NS",
        "DRREDDY.NS", "EIDPARRY.NS", "EIHOTEL.NS", "EDELWEISS.NS",
        "EICHERMOT.NS", "ELGIEQUIP.NS", "EMAMILTD.NS", "ENDURANCE.NS",
        "ENGINERSIN.NS", "EQUITAS.NS", "ERIS.NS", "ESCORTS.NS",
        "ESSELPACK.NS", "EXIDEIND.NS", "FDC.NS", "FEDERALBNK.NS",
        "FINEORG.NS", "FINCABLES.NS", "FINPIPE.NS", "FSL.NS",
        "FORTIS.NS", "FCONSUMER.NS", "FLFL.NS", "FRETAIL.NS",
        "GAIL.NS", "GEPIL.NS", "GET&D.NS", "GHCL.NS",
        "GMRINFRA.NS", "GALAXYSURF.NS", "GDL.NS", "GAYAPROJ.NS",
        "GICRE.NS", "GILLETTE.NS", "GSKCONS.NS", "GLAXO.NS",
        "GLENMARK.NS", "GODFRYPHLP.NS", "GODREJAGRO.NS", "GODREJCP.NS",
        "GODREJIND.NS", "GODREJPROP.NS", "GRANULES.NS", "GRAPHITE.NS",
        "GRASIM.NS", "GESHIP.NS", "GREAVESCOT.NS", "GRINDWELL.NS",
        "GRUH.NS", "GUJALKALI.NS", "GUJFLUORO.NS", "GUJGASLTD.NS",
        "GMDCLTD.NS", "GNFC.NS", "GPPL.NS", "GSFC.NS",
        "GSPL.NS", "GULFOILLUB.NS", "HEG.NS", "HCLTECH.NS",
        "HDFCAMC.NS", "HDFCBANK.NS", "HDFCLIFE.NS", "HATHWAY.NS",
        "HATSUN.NS", "HAVELLS.NS", "HEIDELBERG.NS", "HERITGFOOD.NS",
        "HEROMOTOCO.NS", "HEXAWARE.NS", "HFCL.NS", "HSCL.NS",
        "HIMATSEIDE.NS", "HINDALCO.NS", "HAL.NS", "HINDCOPPER.NS",
        "HINDPETRO.NS", "HINDUNILVR.NS", "HINDZINC.NS", "HONAUT.NS",
        "HUDCO.NS", "HDFC.NS", "ICICIBANK.NS", "ICICIGI.NS",
        "ICICIPRULI.NS", "ISEC.NS", "ICRA.NS", "IDBI.NS",
        "IDFCFIRSTB.NS", "IDFC.NS", "IFBIND.NS", "IFCI.NS",
        "IRB.NS", "IRCON.NS", "ITC.NS", "ITDCEM.NS",
        "ITI.NS", "INDIACEM.NS", "ITDC.NS", "IBULHSGFIN.NS",
        "IBULISL.NS", "IBREALEST.NS", "IBVENTURES.NS", "INDIANB.NS",
        "IEX.NS", "INDHOTEL.NS", "IOC.NS", "IOB.NS",
        "INDOSTAR.NS", "INDOCO.NS", "IGL.NS", "INDUSINDBK.NS",
        "INFIBEAM.NS", "NAUKRI.NS", "INFY.NS", "INOXLEISUR.NS",
        "INOXWIND.NS", "INTELLECT.NS", "INDIGO.NS", "IPCALAB.NS",
        "JBCHEPHARM.NS", "JKCEMENT.NS", "JKLAKSHMI.NS", "JKPAPER.NS",
        "JKTYRE.NS", "JMFINANCIL.NS", "JSWENERGY.NS", "JSWSTEEL.NS",
        "JAGRAN.NS", "JAICORPLTD.NS", "JISLJALEQS.NS", "JPASSOCIAT.NS",
        "J&KBANK.NS", "JAMNAAUTO.NS", "JINDALSAW.NS", "JSLHISAR.NS",
        "JSL.NS", "JINDALSTEL.NS", "JUBLFOOD.NS", "JUBILANT.NS",
        "JUSTDIAL.NS", "JYOTHYLAB.NS", "KPRMILL.NS", "KEI.NS",
        "KIOCL.NS", "KNRCON.NS", "KRBL.NS", "KAJARIACER.NS",
        "KALPATPOWR.NS", "KANSAINER.NS", "KTKBANK.NS", "KARURVYSYA.NS",
        "KSCL.NS", "KEC.NS", "KIRLOSENG.NS", "KOLTEPATIL.NS",
        "KOTAKBANK.NS", "L&TFH.NS", "LTTS.NS", "LICHSGFIN.NS",
        "LAXMIMACH.NS", "LAKSHVILAS.NS", "LTI.NS", "LT.NS",
        "LAURUSLABS.NS", "LEMONTREE.NS", "LINDEINDIA.NS", "LUPIN.NS",
        "LUXIND.NS", "MASFIN.NS", "MMTC.NS", "MOIL.NS",
        "MRF.NS", "MAGMA.NS", "MGL.NS", "MAHSCOOTER.NS",
        "MAHSEAMLES.NS", "M&MFIN.NS", "M&M.NS", "MAHINDCIE.NS",
        "MHRIL.NS", "MAHLOG.NS", "MANAPPURAM.NS", "MRPL.NS",
        "MARICO.NS", "MARUTI.NS", "MFSL.NS", "MAXINDIA.NS",
        "MINDTREE.NS", "MINDACORP.NS", "MINDAIND.NS", "MONSANTO.NS",
        "MOTHERSUMI.NS", "MOTILALOFS.NS", "MPHASIS.NS", "MUTHOOTFIN.NS",
        "NATCOPHARM.NS", "NBCC.NS", "NCC.NS", "NESCO.NS",
        "NHPC.NS", "NIITTECH.NS", "NLCINDIA.NS", "NMDC.NS",
        "NTPC.NS", "NH.NS", "NATIONALUM.NS", "NFL.NS",
        "NBVENTURES.NS", "NAVINFLUOR.NS", "NETWORK18.NS", "NILKAMAL.NS",
        "OBEROIRLTY.NS", "ONGC.NS", "OIL.NS", "OMAXE.NS",
        "OFSS.NS", "ORIENTCEM.NS", "ORIENTELEC.NS", "PCJEWELLER.NS",
        "PIIND.NS", "PNBHOUSING.NS", "PNCINFRA.NS", "PTC.NS",
        "PVR.NS", "PAGEIND.NS", "PARAGMILK.NS", "PERSISTENT.NS",
        "PETRONET.NS", "PFIZER.NS", "PHILIPCARB.NS", "PHOENIXLTD.NS",
        "PIDILITIND.NS", "PEL.NS", "PFC.NS", "POWERGRID.NS",
        "PRAJIND.NS", "PRESTIGE.NS", "PRSMJOHNSN.NS", "PGHL.NS",
        "PGHH.NS", "PNB.NS", "QUESS.NS", "RBLBANK.NS",
        "RECLTD.NS", "RITES.NS", "RADICO.NS", "RAIN.NS",
        "RAJESHEXPO.NS", "RALLIS.NS", "RKFORGE.NS", "RCF.NS",
        "RAYMOND.NS", "REDINGTON.NS", "RELAXO.NS", "RHFL.NS",
        "RELIANCE.NS", "RELINFRA.NS", "RNAM.NS", "RPOWER.NS",
        "REPCOHOME.NS", "RUPA.NS", "SHK.NS", "SBILIFE.NS",
        "SJVN.NS", "SKFINDIA.NS", "SREINFRA.NS", "SRF.NS",
        "SADBHAV.NS", "SANOFI.NS", "SCHAEFFLER.NS", "SIS.NS",
        "SHANKARA.NS", "SHARDACROP.NS", "SFL.NS", "SHILPAMED.NS",
        "SCI.NS", "SHOPERSTOP.NS", "SHREECEM.NS", "RENUKA.NS",
        "SHRIRAMCIT.NS", "SRTRANSFIN.NS", "SIEMENS.NS", "SPTL.NS",
        "SOBHA.NS", "SOLARINDS.NS", "SONATSOFTW.NS", "SOUTHBANK.NS",
        "STARCEMENT.NS", "SBIN.NS", "SAIL.NS", "STRTECH.NS",
        "STAR.NS", "SUDARSCHEM.NS", "SPARC.NS", "SUNPHARMA.NS",
        "SUNTV.NS", "SUNCLAYLTD.NS", "SUNDARMFIN.NS", "SUNDRMFAST.NS",
        "SUNTECK.NS", "SUPRAJIT.NS", "SUPREMEIND.NS", "SUVEN.NS",
        "SUZLON.NS", "SWANENERGY.NS", "SYMPHONY.NS", "SYNGENE.NS",
        "TCNSBRANDS.NS", "TTKPRESTIG.NS", "TVTODAY.NS", "TV18BRDCST.NS",
        "TVSMOTOR.NS", "TAKE.NS", "TNPL.NS", "TATACHEM.NS",
        "TATACOFFEE.NS", "TCS.NS", "TATAELXSI.NS", "TATAGLOBAL.NS",
        "TATAINVEST.NS", "TATAMTRDVR.NS", "TMPV.NS", "TATAPOWER.NS",
        "TATASTEEL.NS", "TEAMLEASE.NS", "TECHM.NS", "NIACL.NS",
        "RAMCOCEM.NS", "THERMAX.NS", "THOMASCOOK.NS", "THYROCARE.NS",
        "TIMETECHNO.NS", "TIMKEN.NS", "TITAN.NS", "TORNTPHARM.NS",
        "TORNTPOWER.NS", "TRENT.NS", "TRIDENT.NS", "TRITURBINE.NS",
        "TIINDIA.NS", "UCOBANK.NS", "UFLEX.NS", "UPL.NS",
        "UJJIVAN.NS", "ULTRACEMCO.NS", "UNIONBANK.NS", "UBL.NS",
        "MCDOWELL-N.NS", "VGUARD.NS", "VMART.NS", "VIPIND.NS",
        "VRLLOG.NS", "VSTIND.NS", "WABAG.NS", "VAKRANGEE.NS",
        "VTL.NS", "VARROC.NS", "VBL.NS", "VEDL.NS",
        "VENKEYS.NS", "VINATIORGA.NS", "IDEA.NS", "VOLTAS.NS",
        "WABCOINDIA.NS", "WELCORP.NS", "WELSPUNIND.NS", "WHIRLPOOL.NS",
        "WIPRO.NS", "WOCKPHARMA.NS", "YESBANK.NS", "ZEEL.NS",
        "ZENSARTECH.NS", "ZYDUSWELL.NS", "ECLERX.NS",
    ],

    # All 28 major + cross forex pairs from the 8 most-traded currencies
    # (AUD, USD, EUR, GBP, JPY, NZD, CAD, CHF) -- the standard "majors +
    # crosses" set.
    "FOREX": [
        "EURUSD=X","GBPUSD=X","AUDUSD=X","NZDUSD=X","USDJPY=X","USDCAD=X","USDCHF=X",
        "EURGBP=X","EURJPY=X","EURAUD=X","EURNZD=X","EURCAD=X","EURCHF=X",
        "GBPJPY=X","GBPAUD=X","GBPNZD=X","GBPCAD=X","GBPCHF=X",
        "AUDJPY=X","AUDNZD=X","AUDCAD=X","AUDCHF=X",
        "NZDJPY=X","NZDCAD=X","NZDCHF=X",
        "CADJPY=X","CADCHF=X",
        "CHFJPY=X",
    ],
}

# Suggested ZigZag deviation % per market / timeframe (starting points --
# tune per-instrument once you see how it behaves in backtests).
DEFAULT_DEVIATION = {
    "AUS": 3.0, "US": 3.0, "INDIA": 3.0, "FOREX": 0.6,
}
