import matplotlib as mpl
import matplotlib.pyplot as plt

# Adjust the Warning Threshold
mpl.rcParams['figure.max_open_warning'] = 50  # Default is 20


def create_plot(data, **kwargs):
    """
    Create a plot using matplotlib.

    Args:
        data: The data to plot.
        **kwargs: Additional keyword arguments for matplotlib.

    Returns:
        A matplotlib figure and axes.
    """
    try:
        fig = plt.figure()
        # Plot creation code using data and kwargs
        plt.plot(data, **kwargs)

        # save the figure to a file, if provided
        if 'save_path' in kwargs:
            save_path = kwargs.pop('save_path')
            fig.savefig(save_path)

        return fig
    finally:
        # always close the figure to avoid resource leaks
        # and to prevent too many open figures
        plt.close(fig)
