<?php
/**
 * Plugin Name: نقشه لجستیک فارسی برای المنتور
 * Description: ویجت فارسی و واکنش‌گرای نقشه جهان، مسیرهای حمل‌ونقل و کارت‌های خدمات برای Elementor.
 * Version: 1.0.0
 * Author: Parsi Logistics Map
 * Text Domain: parsi-logistics-map
 * Requires at least: 6.2
 * Requires PHP: 7.4
 * Elementor tested up to: 3.32
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'PLM_VERSION', '1.0.0' );
define( 'PLM_FILE', __FILE__ );
define( 'PLM_PATH', plugin_dir_path( __FILE__ ) );
define( 'PLM_URL', plugin_dir_url( __FILE__ ) );

/**
 * Bootstrap the plugin after all plugins have loaded.
 */
function plm_bootstrap() {
	if ( ! did_action( 'elementor/loaded' ) ) {
		add_action( 'admin_notices', 'plm_elementor_missing_notice' );
		return;
	}

	add_action( 'wp_enqueue_scripts', 'plm_register_assets' );
	add_action( 'elementor/widgets/register', 'plm_register_widget' );
}
add_action( 'plugins_loaded', 'plm_bootstrap' );

/**
 * Register the front-end stylesheet. Elementor loads it only when the widget is used.
 */
function plm_register_assets() {
	wp_register_style(
		'parsi-logistics-map',
		PLM_URL . 'assets/css/widget.css',
		array(),
		PLM_VERSION
	);
}

/**
 * Register the Elementor widget.
 *
 * @param \Elementor\Widgets_Manager $widgets_manager Widget manager.
 */
function plm_register_widget( $widgets_manager ) {
	require_once PLM_PATH . 'includes/class-plm-logistics-widget.php';
	$widgets_manager->register( new \PLM_Logistics_Widget() );
}

/**
 * Show a clear Persian dependency notice in wp-admin.
 */
function plm_elementor_missing_notice() {
	if ( ! current_user_can( 'activate_plugins' ) ) {
		return;
	}
	?>
	<div class="notice notice-warning is-dismissible">
		<p><?php echo esc_html__( 'برای استفاده از «نقشه لجستیک فارسی»، ابتدا افزونه Elementor را نصب و فعال کنید.', 'parsi-logistics-map' ); ?></p>
	</div>
	<?php
}

