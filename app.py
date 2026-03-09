import streamlit as st
import pandas as pd

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

            # Full merge for match diagnostics
            diagnostic_merge = pd.merge(
                supplier_df,
                local_df,
                on=["Model", "Storage", "Condition"],
                how="outer",
                indicator=True
            )

            matched_df = diagnostic_merge[diagnostic_merge["_merge"] == "both"].copy()
            supplier_only_df = diagnostic_merge[diagnostic_merge["_merge"] == "left_only"].copy()
            local_only_df = diagnostic_merge[diagnostic_merge["_merge"] == "right_only"].copy()

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

                matched_df = matched_df.sort_values(
                    by="Net_Profit_GHS",
                    ascending=False
                ).reset_index(drop=True)

                # Summary metrics
                total_items = len(matched_df)
                avg_profit = matched_df["Net_Profit_GHS"].mean()
                best_profit = matched_df["Net_Profit_GHS"].max()

                metric1, metric2, metric3 = st.columns(3)
                metric1.metric("Matched Devices", total_items)
                metric2.metric("Average Net Profit (GHS)", f"{avg_profit:,.2f}")
                metric3.metric("Best Net Profit (GHS)", f"{best_profit:,.2f}")

                st.write("### Profit Analysis")

                display_df = matched_df.copy()
                display_df["US_Price_USD"] = display_df["US_Price_USD"].map(lambda x: f"{x:,.2f}")
                display_df["Local_Price_GHS"] = display_df["Local_Price_GHS"].map(lambda x: f"{x:,.2f}")
                display_df["Landed_Cost_GHS"] = display_df["Landed_Cost_GHS"].map(lambda x: f"{x:,.2f}")
                display_df["Net_Profit_GHS"] = display_df["Net_Profit_GHS"].map(lambda x: f"{x:,.2f}")

                st.dataframe(display_df.drop(columns=["_merge"]), use_container_width=True)

                st.write("### Top 10 Most Profitable Devices")

                chart_df = matched_df.copy()
                chart_df["Device_Label"] = (
                    chart_df["Model"] + " | " +
                    chart_df["Storage"].astype(str) + " | " +
                    chart_df["Condition"].astype(str)
                )

                top_10 = chart_df.head(10).set_index("Device_Label")[["Net_Profit_GHS"]]
                st.bar_chart(top_10)

                # Download matched results
                csv_data = matched_df.drop(columns=["_merge"]).to_csv(index=False).encode("utf-8")
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
