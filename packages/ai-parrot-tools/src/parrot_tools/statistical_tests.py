"""
StatisticalTestsTool — t-test, ANOVA, chi-square, normality.

Validates whether differences between groups or scenarios are
statistically significant.
"""
from typing import Dict, List, Optional, Type

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy import stats as scipy_stats

from .abstract import AbstractTool, ToolResult


class StatisticalTestInput(BaseModel):
    """Input schema for StatisticalTestsTool."""

    df_name: str = Field(description="Name or alias of the dataset")
    test_type: str = Field(
        description=(
            "Test type: 'ttest', 'anova', 'chi_square', "
            "'mann_whitney', 'kruskal_wallis', 'normality'"
        )
    )
    target_column: str = Field(description="Column to test")
    group_column: Optional[str] = Field(
        default=None,
        description="Categorical column defining groups (required for ttest, anova, etc.)",
    )
    groups: Optional[List[str]] = Field(
        default=None,
        description="Specific group values to compare (default: all groups)",
    )
    alpha: float = Field(default=0.05, description="Significance level")
    alternative: str = Field(
        default="two-sided",
        description="Alternative hypothesis: 'two-sided', 'less', 'greater'",
    )


TEST_DISPATCH = {
    "ttest": "_run_ttest",
    "anova": "_run_anova",
    "chi_square": "_run_chi_square",
    "mann_whitney": "_run_mann_whitney",
    "kruskal_wallis": "_run_kruskal_wallis",
    "normality": "_run_normality",
}


class StatisticalTestsTool(AbstractTool):
    """Run statistical hypothesis tests on dataset groups.

    Supports t-test, ANOVA, chi-square, Mann-Whitney, Kruskal-Wallis,
    and normality tests. Returns test statistic, p-value, effect size,
    and plain-language interpretation.
    """

    args_schema: Type[BaseModel] = StatisticalTestInput

    def __init__(self, **kwargs):
        super().__init__(
            name="statistical_tests",
            description=(
                "Run statistical hypothesis tests (t-test, ANOVA, chi-square, "
                "normality) to validate whether differences between groups "
                "are statistically significant."
            ),
            **kwargs,
        )
        self._parent_agent = None

    def _get_dataframe(self, df_name: str) -> pd.DataFrame:
        """Resolve DataFrame from parent agent."""
        if self._parent_agent and hasattr(self._parent_agent, "dataframes"):
            df = self._parent_agent.dataframes.get(df_name)
            if df is not None:
                return df
        raise ValueError(f"Dataset '{df_name}' not found")

    def _extract_groups(
        self, df: pd.DataFrame, input_data: StatisticalTestInput
    ) -> List[np.ndarray]:
        """Extract group data arrays from DataFrame."""
        if not input_data.group_column:
            raise ValueError("group_column is required for this test")
        if input_data.group_column not in df.columns:
            raise ValueError(f"Group column '{input_data.group_column}' not found")

        group_values = input_data.groups
        if group_values is None:
            group_values = df[input_data.group_column].unique().tolist()

        groups = []
        for gv in group_values:
            mask = df[input_data.group_column] == gv
            data = df.loc[mask, input_data.target_column].dropna().values.astype(float)
            if len(data) > 0:
                groups.append(data)

        return groups, group_values

    @staticmethod
    def _cohens_d(group1: np.ndarray, group2: np.ndarray) -> float:
        """Cohen's d for two independent groups."""
        n1, n2 = len(group1), len(group2)
        var1, var2 = group1.var(ddof=1), group2.var(ddof=1)
        pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
        if pooled_std == 0:
            return 0.0
        return float((group1.mean() - group2.mean()) / pooled_std)

    @staticmethod
    def _eta_squared(f_stat: float, df_between: int, df_within: int) -> float:
        """Eta-squared for ANOVA."""
        return float(
            (f_stat * df_between) / (f_stat * df_between + df_within)
        )

    def _interpret_effect_size(self, d: float) -> str:
        """Interpret Cohen's d."""
        ad = abs(d)
        if ad < 0.2:
            return "negligible"
        elif ad < 0.5:
            return "small"
        elif ad < 0.8:
            return "medium"
        else:
            return "large"

    def _interpret_pvalue(
        self, p_value: float, alpha: float, test_name: str,
        metric: str, groups: List[str]
    ) -> str:
        """Generate plain-language interpretation."""
        group_str = " and ".join(str(g) for g in groups[:4])
        if p_value < alpha:
            return (
                f"The difference in {metric} between {group_str} "
                f"is statistically significant (p={p_value:.4f} < {alpha})"
            )
        return (
            f"No statistically significant difference in {metric} "
            f"between {group_str} (p={p_value:.4f} >= {alpha})"
        )

    def _run_ttest(
        self, df: pd.DataFrame, input_data: StatisticalTestInput
    ) -> ToolResult:
        """Run independent two-sample t-test."""
        groups, group_names = self._extract_groups(df, input_data)
        if len(groups) < 2:
            return ToolResult(
                success=False, result={},
                error="t-test requires exactly 2 groups with data",
            )
        g1, g2 = groups[0], groups[1]

        stat, p_value = scipy_stats.ttest_ind(g1, g2, alternative=input_data.alternative)
        d = self._cohens_d(g1, g2)
        effect_label = self._interpret_effect_size(d)
        interpretation = self._interpret_pvalue(
            p_value, input_data.alpha, "T-Test",
            input_data.target_column, group_names[:2],
        )

        lines = [
            f"T-Test: {input_data.target_column} by {input_data.group_column} "
            f"({group_names[0]} vs {group_names[1]})",
            f"  t-statistic: {stat:.4f}",
            f"  p-value: {p_value:.4f}",
            f"  Effect size (Cohen's d): {d:.2f} ({effect_label})",
            "",
            f"Interpretation: {interpretation}",
        ]
        return ToolResult(success=True, result="\n".join(lines))

    def _run_anova(
        self, df: pd.DataFrame, input_data: StatisticalTestInput
    ) -> ToolResult:
        """Run one-way ANOVA."""
        groups, group_names = self._extract_groups(df, input_data)
        if len(groups) < 2:
            return ToolResult(
                success=False, result={},
                error="ANOVA requires at least 2 groups with data",
            )

        f_stat, p_value = scipy_stats.f_oneway(*groups)
        df_between = len(groups) - 1
        df_within = sum(len(g) for g in groups) - len(groups)
        eta_sq = self._eta_squared(f_stat, df_between, df_within)
        interpretation = self._interpret_pvalue(
            p_value, input_data.alpha, "ANOVA",
            input_data.target_column, group_names,
        )

        lines = [
            f"One-Way ANOVA: {input_data.target_column} by {input_data.group_column}",
            f"  F-statistic: {f_stat:.4f}",
            f"  p-value: {p_value:.4f}",
            f"  Effect size (eta-squared): {eta_sq:.4f}",
            f"  Groups: {', '.join(str(g) for g in group_names)}",
            "",
            f"Interpretation: {interpretation}",
        ]
        return ToolResult(success=True, result="\n".join(lines))

    def _run_chi_square(
        self, df: pd.DataFrame, input_data: StatisticalTestInput
    ) -> ToolResult:
        """Run chi-squared test of independence."""
        if not input_data.group_column:
            return ToolResult(
                success=False, result={},
                error="group_column is required for chi-square test",
            )

        contingency = pd.crosstab(
            df[input_data.target_column], df[input_data.group_column]
        )
        chi2, p_value, dof, expected = scipy_stats.chi2_contingency(contingency)

        lines = [
            f"Chi-Square Test: {input_data.target_column} vs {input_data.group_column}",
            f"  Chi-square statistic: {chi2:.4f}",
            f"  p-value: {p_value:.4f}",
            f"  Degrees of freedom: {dof}",
            "",
        ]
        if p_value < input_data.alpha:
            lines.append(
                f"Interpretation: Significant association between "
                f"{input_data.target_column} and {input_data.group_column} "
                f"(p={p_value:.4f} < {input_data.alpha})"
            )
        else:
            lines.append(
                f"Interpretation: No significant association between "
                f"{input_data.target_column} and {input_data.group_column} "
                f"(p={p_value:.4f} >= {input_data.alpha})"
            )
        return ToolResult(success=True, result="\n".join(lines))

    def _run_mann_whitney(
        self, df: pd.DataFrame, input_data: StatisticalTestInput
    ) -> ToolResult:
        """Run Mann-Whitney U test (non-parametric two-sample)."""
        groups, group_names = self._extract_groups(df, input_data)
        if len(groups) < 2:
            return ToolResult(
                success=False, result={},
                error="Mann-Whitney requires exactly 2 groups with data",
            )
        g1, g2 = groups[0], groups[1]
        stat, p_value = scipy_stats.mannwhitneyu(
            g1, g2, alternative=input_data.alternative
        )
        interpretation = self._interpret_pvalue(
            p_value, input_data.alpha, "Mann-Whitney",
            input_data.target_column, group_names[:2],
        )

        lines = [
            f"Mann-Whitney U Test: {input_data.target_column} by {input_data.group_column}",
            f"  U-statistic: {stat:.4f}",
            f"  p-value: {p_value:.4f}",
            "",
            f"Interpretation: {interpretation}",
        ]
        return ToolResult(success=True, result="\n".join(lines))

    def _run_kruskal_wallis(
        self, df: pd.DataFrame, input_data: StatisticalTestInput
    ) -> ToolResult:
        """Run Kruskal-Wallis test (non-parametric ANOVA)."""
        groups, group_names = self._extract_groups(df, input_data)
        if len(groups) < 2:
            return ToolResult(
                success=False, result={},
                error="Kruskal-Wallis requires at least 2 groups with data",
            )
        stat, p_value = scipy_stats.kruskal(*groups)
        interpretation = self._interpret_pvalue(
            p_value, input_data.alpha, "Kruskal-Wallis",
            input_data.target_column, group_names,
        )

        lines = [
            f"Kruskal-Wallis Test: {input_data.target_column} by {input_data.group_column}",
            f"  H-statistic: {stat:.4f}",
            f"  p-value: {p_value:.4f}",
            "",
            f"Interpretation: {interpretation}",
        ]
        return ToolResult(success=True, result="\n".join(lines))

    def _run_normality(
        self, df: pd.DataFrame, input_data: StatisticalTestInput
    ) -> ToolResult:
        """Run Shapiro-Wilk normality test."""
        if input_data.target_column not in df.columns:
            return ToolResult(
                success=False, result={},
                error=f"Column '{input_data.target_column}' not found",
            )
        data = df[input_data.target_column].dropna().values.astype(float)
        if len(data) < 3:
            return ToolResult(
                success=False, result={},
                error="At least 3 observations needed for normality test",
            )
        # Shapiro-Wilk has a sample size limit of 5000
        if len(data) > 5000:
            data = data[:5000]

        stat, p_value = scipy_stats.shapiro(data)

        lines = [
            f"Shapiro-Wilk Normality Test: {input_data.target_column}",
            f"  W-statistic: {stat:.4f}",
            f"  p-value: {p_value:.4f}",
            "",
        ]
        if p_value < input_data.alpha:
            lines.append(
                f"Interpretation: The distribution of {input_data.target_column} "
                f"is significantly non-normal (p={p_value:.4f} < {input_data.alpha})"
            )
        else:
            lines.append(
                f"Interpretation: Cannot reject normality for "
                f"{input_data.target_column} (p={p_value:.4f} >= {input_data.alpha})"
            )
        return ToolResult(success=True, result="\n".join(lines))

    async def _execute(self, **kwargs) -> ToolResult:
        """Execute the selected statistical test."""
        try:
            input_data = StatisticalTestInput(**kwargs)
        except Exception as e:
            return ToolResult(success=False, result={}, error=f"Invalid input: {e}")

        try:
            df = self._get_dataframe(input_data.df_name)
        except ValueError as e:
            return ToolResult(success=False, result={}, error=str(e))

        method_name = TEST_DISPATCH.get(input_data.test_type)
        if not method_name:
            return ToolResult(
                success=False, result={},
                error=f"Unknown test type: '{input_data.test_type}'. "
                f"Available: {list(TEST_DISPATCH.keys())}",
            )

        try:
            method = getattr(self, method_name)
            return method(df, input_data)
        except Exception as e:
            return ToolResult(
                success=False, result={},
                error=f"Error running {input_data.test_type}: {e}",
            )
