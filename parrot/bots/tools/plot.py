import matplotlib as mpl
import matplotlib.pyplot as plt

# Adjust the Warning Threshold
mpl.rcParams['figure.max_open_warning'] = 50  # Default is 20


def create_plot(
    dataframe,
    x=None,
    y=None,
    kind='line',
    title=None,
    xlabel=None,
    ylabel=None,
    figsize=(10, 6),
    save_path=None
):
    """Create and save a plot with proper cleanup."""
    import matplotlib.pyplot as plt

    try:
        # Create the plot
        fig, ax = plt.subplots(figsize=figsize)

        if kind == 'line':
            dataframe.plot(x=x, y=y, kind=kind, ax=ax)
        elif kind == 'bar':
            dataframe.plot(x=x, y=y, kind=kind, ax=ax)
        # Add more plot types as needed

        # Add labels and title
        if xlabel:
            ax.set_xlabel(xlabel)
        if ylabel:
            ax.set_ylabel(ylabel)
        if title:
            ax.set_title(title)

        # Save if path provided
        if save_path:
            plt.savefig(save_path, bbox_inches='tight')
            return save_path

        return fig
    finally:
        # Always close the figure to prevent memory leaks
        plt.close(fig)
