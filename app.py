import streamlit as st
import pandas as pd
from rapidfuzz import process, fuzz

st.set_page_config(page_title="Retail Arbitrage Dashboard", layout="wide")

st.title("Retail Arbitrage Dashboard")
st.write("Upload your supplier and local market CSV files to calculate profit margins.")

# Sidebar inputs
st.sidebar.header("Cost Inputs")

exchange_rate = st.sidebar.number_input(
    "Exchange Rate (GHS per USD)",
    min_value=0.0,
    value=15.5,
    step=0.1
)

shipping_cost = st.sidebar.number_input(
    "Shipping Cost (GHS)",
    min_value=0.0,
    value=0.0,
    step=10.0
)

customs_fee = st.sidebar.number_input(
    "Customs Fee (GHS)",
    min_value=0.0,
    value=0.0,
    step=10.0
)

st.subheader("Upload Data Files")

col1, col2 = st.columns(2)

with col1:
    supplier_file = st.file_uploader(
        "Upload Supplier CSV",
        type=["csv"],
        key="supplier_csv"
    )

with col2:
    local_file = st.file_uploader(
        "Upload Local Market CSV",
        type=["csv"],
        key="local_csv"
    )

required_supplier_cols = {"Model", "Storage", "Condition", "US_Price_USD"}
required_local_cols = {"Model", "Storage", "Condition", "Local_Price_GHS"}


def clean_dataframe(df):
    # Clean column names
    df.columns = df.columns.str.strip()

    # Clean key text columns if present
    key_cols = ["Model", "Storage", "Condition"]
    for col in key_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.strip()
                .str.replace(r"\s+", " ", regex=True)
                .str.title()
            )

    return df


if supplier_file is None or local_file is None:
    st.info("Please upload both CSV files to continue.")
else:
    try:
        supplier_df = pd.read_csv(supplier_file)
        local_df = pd.read_csv(local_file)

        supplier_df = clean_dataframe(supplier_df)
        local_df = clean_dataframe(local_df)

        st.success("Both CSV files uploaded successfully.")

        st.write("### Supplier Data Preview")
        st.dataframe(supplier_df.head(), use_container_width=True)

        st.write("### Local Market Data Preview")
        st.dataframe(local_df.head(), use_container_width=True)

        missing_supplier = required_supplier_cols - set(supplier_df.columns)
        missing_local = required_local_cols - set(local_df.columns)

        if missing_supplier:
            st.error(f"Supplier CSV is missing these columns: {sorted(missing_supplier)}")

        if missing_local:
            st.error(f"Local Market CSV is missing these columns: {sorted(missing_local)}")

        if not missing_supplier and not missing_local:
            # Convert price columns safely
            supplier_df["US_Price_USD"] = pd.to_numeric(supplier_df["US_Price_USD"], errors="coerce")
            local_df["Local_Price_GHS"] = pd.to_numeric(local_df["Local_Price_GHS"], errors="coerce")

            # Keep track of invalid rows
            invalid_supplier_rows = supplier_df[supplier_df["US_Price_USD"].isna()]
            invalid_local_rows = local_df[local_df["Local_Price_GHS"].isna()]

            supplier_df = supplier_df.dropna(subset=["US_Price_USD"])
            local_df = local_df.dropna(subset=["Local_Price_GHS"])
            
            # --- Fuzzy Matching Logic ---
            # 1. First, get exact matches
            exact_merge = pd.merge(
                supplier_df,
                local_df,
                on=["Model", "Storage", "Condition"],
                how="inner"
            )
            
            # 2. Identify unmatched rows
            exact_keys_supplier = exact_merge[["Model", "Storage", "Condition"]].drop_duplicates()
            unmatched_supplier = pd.merge(supplier_df, exact_keys_supplier, indicator=True, how='left').query('_merge=="left_only"').drop('_merge', axis=1)
            
            exact_keys_local = exact_merge[["Model", "Storage", "Condition"]].drop_duplicates()
            unmatched_local = pd.merge(local_df, exact_keys_local, indicator=True, how='left').query('_merge=="left_only"').drop('_merge', axis=1)

            fuzzy_matches = []
            
            # 3. Apply fuzzy matching ONLY to unmatched rows where Storage and Condition match exactly
            if not unmatched_supplier.empty and not unmatched_local.empty:
               local_models = unmatched_local["Model"].unique().tolist()
               
               for idx, s_row in unmatched_supplier.iterrows():
                   s_model = s_row["Model"]
                   s_storage = s_row["Storage"]
                   s_condition = s_row["Condition"]
                   
                   # Filter local candidates that have the exact same storage and condition
                   candidates = unmatched_local[
                       (unmatched_local["Storage"] == s_storage) & 
                       (unmatched_local["Condition"] == s_condition)
                   ]["Model"].tolist()
                   
                   if candidates:
                       # Find best match using token_sort_ratio to handle word order changes
                       best_match, score = process.extractOne(s_model, candidates, scorer=fuzz.token_sort_ratio)
                       
                       # Set a threshold (e.g., 85)
                       if score >= 85:
                           # Find the corresponding local row
                           l_row = unmatched_local[
                               (unmatched_local["Model"] == best_match) & 
                               (unmatched_local["Storage"] == s_storage) & 
                               (unmatched_local["Condition"] == s_condition)
                           ].iloc[0]
                           
                           # Combine data
                           combined_row = s_row.to_dict()
                           combined_row["Local_Price_GHS"] = l_row["Local_Price_GHS"]
                           combined_row["Matched_Local_Model"] = best_match # Keep track for diagnostics
                           combined_row["Fuzzy_Score"] = score
                           fuzzy_matches.append(combined_row)
            
            fuzzy_df = pd.DataFrame(fuzzy_matches)
            
            # Combine exact matches and fuzzy matches
            if not fuzzy_df.empty:
                # Add columns to exact_merge to match fuzzy_df schema
                exact_merge["Matched_Local_Model"] = exact_merge["Model"]
                exact_merge["Fuzzy_Score"] = 100
                matched_df = pd.concat([exact_merge, fuzzy_df], ignore_index=True)
            else:
                matched_df = exact_merge.copy()

            # --- Full Diagnostics Merge (To find what's truly left over) ---
            # To figure out true supplier_only and local_only, we need to look at what's in matched_df
            
            if not matched_df.empty:
                # Remove matched items from supplier
                matched_s_keys = matched_df[["Model", "Storage", "Condition"]].drop_duplicates()
                supplier_only_df = pd.merge(supplier_df, matched_s_keys, indicator=True, how='left').query('_merge=="left_only"').drop('_merge', axis=1)
                
                # Remove matched items from local (remember local models might have been fuzzy matched)
                # For local, the join keys in matched_df are Matched_Local_Model, Storage, Condition (or Model if exact)
                local_match_keys = matched_df.copy()
                if "Matched_Local_Model" in local_match_keys.columns:
                     local_match_keys["Model"] = local_match_keys["Matched_Local_Model"]
                local_match_keys = local_match_keys[["Model", "Storage", "Condition"]].drop_duplicates()
                
                local_only_df = pd.merge(local_df, local_match_keys, indicator=True, how='left').query('_merge=="left_only"').drop('_merge', axis=1)
            else:
                supplier_only_df = supplier_df.copy()
                local_only_df = local_df.copy()


            if matched_df.empty:
                st.warning(
                    "No matching rows were found after merging. "
                    "Check that Model, Storage, and Condition values match across both files."
                )
            else:
                matched_df["Landed_Cost_GHS"] = (
                    matched_df["US_Price_USD"] * exchange_rate
                    + shipping_cost
                    + customs_fee
                )

                matched_df["Net_Profit_GHS"] = (
                    matched_df["Local_Price_GHS"] - matched_df["Landed_Cost_GHS"]
                )

                matched_df["ROI_%"] = (
                    matched_df["Net_Profit_GHS"] / matched_df["Landed_Cost_GHS"]
                ) * 100

                matched_df["Margin_%"] = (
                    matched_df["Net_Profit_GHS"] / matched_df["Local_Price_GHS"]
                ) * 100

                matched_df = matched_df.sort_values(
                    by="Net_Profit_GHS",
                    ascending=False
                ).reset_index(drop=True)

                # At-A-Glance KPI Dashboard metrics
                profitable_items = matched_df[matched_df["Net_Profit_GHS"] > 0]
                total_potential_profit = profitable_items["Net_Profit_GHS"].sum()
                total_initial_capital = profitable_items["Landed_Cost_GHS"].sum()
                
                best_profit = matched_df["Net_Profit_GHS"].max()
                avg_roi = matched_df["ROI_%"].mean()

                st.write("### 🚀 At-A-Glance KPI Dashboard")
                kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                
                kpi1.metric(
                    "Total Potential Profit", 
                    f"GH\u20b5{total_potential_profit:,.2f}", 
                    help="Total profit if you bought one of every profitable item."
                )
                kpi2.metric(
                    "Initial Capital Required", 
                    f"GH\u20b5{total_initial_capital:,.2f}",
                    help="Total cost (incl. shipping & fees) to buy all profitable inventory."
                )
                kpi3.metric(
                    "Highest Single Item Profit", 
                    f"GH\u20b5{best_profit:,.2f}",
                    help="The absolute max profit from a single matched item."
                )
                kpi4.metric(
                    "Average ROI", 
                    f"{avg_roi:,.2f}%",
                    help="The average return on investment across all items."
                )
                
                st.divider()

                # Original Summary metrics
                total_items = len(matched_df)
                avg_profit = matched_df["Net_Profit_GHS"].mean()
                best_roi = matched_df["ROI_%"].max()
                avg_margin = matched_df["Margin_%"].mean()

                st.write("### Detailed Overview")
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Matched Devices", total_items)
                col_b.metric("Best Net Profit (GHS)", f"{best_profit:,.2f}")
                col_c.metric("Avg Net Profit (GHS)", f"{avg_profit:,.2f}")

                col_d, col_e, col_f = st.columns(3)
                col_d.metric("Best ROI", f"{best_roi:,.2f}%")
                col_e.metric("Avg ROI", f"{avg_roi:,.2f}%")
                col_f.metric("Avg Margin", f"{avg_margin:,.2f}%")

                st.divider()

                st.write("### Profit Analysis Table")
                st.caption("Sorted by highest Net Profit. Green = higher profit. Blue = higher ROI.")

                styled_df = matched_df.copy()
                if "Matched_Local_Model" in styled_df.columns:
                    styled_df.drop(columns=["Matched_Local_Model", "Fuzzy_Score"], inplace=True, errors="ignore")
                if "_merge" in styled_df.columns:
                    styled_df.drop(columns=["_merge"], inplace=True, errors="ignore")

                st.dataframe(
                    styled_df.style.format({
                        "US_Price_USD": "${:,.2f}",
                        "Local_Price_GHS": "GH\u20b5{:,.2f}",
                        "Landed_Cost_GHS": "GH\u20b5{:,.2f}",
                        "Net_Profit_GHS": "GH\u20b5{:,.2f}",
                        "ROI_%": "{:,.2f}%",
                        "Margin_%": "{:,.2f}%",
                    }).background_gradient(subset=["Net_Profit_GHS"], cmap="Greens")
                     .background_gradient(subset=["ROI_%"], cmap="Blues"),
                    use_container_width=True
                )

                st.write("### Top 10 Most Profitable Devices")

                chart_df = matched_df.copy()
                chart_df["Device_Label"] = (
                    chart_df["Model"] + " | " +
                    chart_df["Storage"].astype(str) + " | " +
                    chart_df["Condition"].astype(str)
                )

                top10_profit = chart_df.head(10).set_index("Device_Label")[["Net_Profit_GHS"]]
                top10_roi = chart_df.sort_values(by="ROI_%", ascending=False).head(10).set_index("Device_Label")[["ROI_%"]]

                # Make sure plotly is available
                try:
                    import plotly.express as px
                except ImportError:
                    st.error("Please install plotly: pip install plotly")
                    st.stop()
                    
                chart_col1, chart_col2 = st.columns(2)
                with chart_col1:
                    st.write("**By Absolute Profit (GHS)**")
                    fig_profit = px.bar(
                        top10_profit.reset_index(), 
                        x="Net_Profit_GHS", 
                        y="Device_Label", 
                        orientation='h',
                        labels={"Net_Profit_GHS": "Net Profit (GHS)", "Device_Label": "Device"},
                        color="Net_Profit_GHS",
                    )
                    fig_profit.update_layout(yaxis={'categoryorder':'total ascending'})
                    st.plotly_chart(fig_profit, use_container_width=True)
                    
                with chart_col2:
                    st.write("**By ROI (%)**")
                    fig_roi = px.bar(
                        top10_roi.reset_index(), 
                        x="ROI_%", 
                        y="Device_Label", 
                        orientation='h',
                        labels={"ROI_%": "Return on Investment (%)", "Device_Label": "Device"},
                        color="ROI_%",
                        color_continuous_scale="Blues"
                    )
                    fig_roi.update_layout(yaxis={'categoryorder':'total ascending'})
                    st.plotly_chart(fig_roi, use_container_width=True)

                st.divider()

                st.write("### Cost Breakdown of Top 10 Profitable Devices")
                st.caption("Shows the breakdown of your total costs (Device + Shipping + Customs) compared to Local Market Price.")

                # Calculate components of landed cost in GHS
                top10_cost_df = chart_df.head(10).copy()
                top10_cost_df["Device_Cost_GHS"] = top10_cost_df["US_Price_USD"] * exchange_rate
                top10_cost_df["Shipping_Cost_GHS"] = shipping_cost
                top10_cost_df["Customs_Fee_GHS"] = customs_fee

                # Melt the dataframe for Plotly stacked bar chart
                cost_breakdown_melted = top10_cost_df.melt(
                    id_vars=["Device_Label", "Local_Price_GHS", "Net_Profit_GHS"],
                    value_vars=["Device_Cost_GHS", "Shipping_Cost_GHS", "Customs_Fee_GHS"],
                    var_name="Cost_Type",
                    value_name="Amount_GHS"
                )

                # Clean up labels for display
                cost_breakdown_melted["Cost_Type"] = cost_breakdown_melted["Cost_Type"].replace({
                    "Device_Cost_GHS": "Device Cost",
                    "Shipping_Cost_GHS": "Shipping",
                    "Customs_Fee_GHS": "Customs"
                })

                fig_costs = px.bar(
                    cost_breakdown_melted,
                    x="Amount_GHS",
                    y="Device_Label",
                    color="Cost_Type",
                    orientation="h",
                    title="Total Landed Cost Breakdown",
                    labels={"Amount_GHS": "Cost Amount (GHS)", "Device_Label": "Device", "Cost_Type": "Cost Component"},
                    color_discrete_map={
                        "Device Cost": "#1f77b4", # blue
                        "Shipping": "#ff7f0e",    # orange
                        "Customs": "#d62728"      # red
                    }
                )
                
                # Add hover data to show the final local price constraint
                fig_costs.update_traces(
                    hovertemplate="<b>%{y}</b><br>%{data.name}: GH\u20b5%{x:,.2f}<br>"
                )
                fig_costs.update_layout(yaxis={'categoryorder':'total ascending'})

                st.plotly_chart(fig_costs, use_container_width=True)

                st.divider()

                # Download matched results
                csv_data = matched_df.drop(columns=["_merge"], errors="ignore").to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download Profit Analysis CSV",
                    data=csv_data,
                    file_name="profit_analysis.csv",
                    mime="text/csv"
                )

            # Diagnostics section
            st.write("### Data Quality Diagnostics")

            diag1, diag2, diag3, diag4 = st.columns(4)
            diag1.metric("Matched Rows", len(matched_df))
            diag2.metric("Supplier Only Rows", len(supplier_only_df))
            diag3.metric("Local Only Rows", len(local_only_df))
            diag4.metric(
                "Invalid Price Rows",
                len(invalid_supplier_rows) + len(invalid_local_rows)
            )

            if not invalid_supplier_rows.empty:
                st.write("#### Supplier Rows with Invalid US_Price_USD")
                st.dataframe(invalid_supplier_rows, use_container_width=True)

            if not invalid_local_rows.empty:
                st.write("#### Local Rows with Invalid Local_Price_GHS")
                st.dataframe(invalid_local_rows, use_container_width=True)

            if not supplier_only_df.empty:
                st.write("#### Supplier Rows Without Local Market Match")
                st.dataframe(
                    supplier_only_df[["Model", "Storage", "Condition", "US_Price_USD"]],
                    use_container_width=True
                )

            if not local_only_df.empty:
                st.write("#### Local Market Rows Without Supplier Match")
                st.dataframe(
                    local_only_df[["Model", "Storage", "Condition", "Local_Price_GHS"]],
                    use_container_width=True
                )

    except Exception as e:
        st.error(f"An error occurred while processing the files: {e}")
