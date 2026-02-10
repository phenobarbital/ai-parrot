import yfinance as yf
import json

def explore_yfinance():
    ticker = yf.Ticker("AAPL")
    
    # 1. Sector/Industry from info
    print("\n--- Info (Sector/Industry) ---")
    info = ticker.info
    print(f"Sector: {info.get('sector')}")
    print(f"Industry: {info.get('industry')}")
    
    # 2. Options Data for Put/Call Ratio
    print("\n--- Options Data ---")
    try:
        exps = ticker.options
        if exps:
            print(f"Expirations: {exps[:3]}...")
            # Get nearest expiration
            chain = ticker.option_chain(exps[0])
            calls = chain.calls
            puts = chain.puts
            
            total_call_vol = calls['volume'].sum()
            total_put_vol = puts['volume'].sum()
            total_call_oi = calls['openInterest'].sum()
            total_put_oi = puts['openInterest'].sum()
            
            print(f"Nearest Expiration: {exps[0]}")
            print(f"Total Call Volume: {total_call_vol}")
            print(f"Total Put Volume: {total_put_vol}")
            if total_call_vol > 0:
                print(f"Put/Call Volume Ratio: {total_put_vol / total_call_vol:.4f}")
                
            print(f"Total Call OI: {total_call_oi}")
            print(f"Total Put OI: {total_put_oi}")
            if total_call_oi > 0:
                print(f"Put/Call OI Ratio: {total_put_oi / total_call_oi:.4f}")
        else:
            print("No options data found.")
    except Exception as e:
        print(f"Error fetching options: {e}")

if __name__ == "__main__":
    explore_yfinance()
